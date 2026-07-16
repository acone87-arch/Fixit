import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.database import get_db
from app.models.core import User, UserRole
from app.models.warehouse import Part, Warehouse, WarehouseStock
from app.schemas.warehouse import PartCreate, PartOut, StockItem, StockMovementCreate, WarehouseOut
from app.services.stock_service import InsufficientStockError, receive_stock, transfer_stock

router = APIRouter(prefix="/api/warehouses", tags=["warehouses"])
parts_router = APIRouter(prefix="/api/parts", tags=["parts"])


@router.get("", response_model=list[WarehouseOut])
async def list_warehouses(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(Warehouse).order_by(Warehouse.name))).all()


@router.get("/{warehouse_id}/stock", response_model=list[StockItem])
async def warehouse_stock(
    warehouse_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Техник может смотреть только свой мобильный склад; админ/диспетчер — любой.
    if user.role == UserRole.technician:
        warehouse = await db.get(Warehouse, warehouse_id)
        if not warehouse or warehouse.owner_user_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Доступен только собственный склад")

    rows = (
        await db.execute(
            select(WarehouseStock, Part)
            .join(Part, Part.id == WarehouseStock.part_id)
            .where(WarehouseStock.warehouse_id == warehouse_id)
            .order_by(Part.name)
        )
    ).all()
    return [
        StockItem(
            part_id=part.id,
            article=part.article,
            name=part.name,
            quantity=stock.quantity,
            min_critical_qty=part.min_critical_qty,
            is_critical=stock.quantity <= part.min_critical_qty,
        )
        for stock, part in rows
    ]


@router.post("/movements/receive", status_code=status.HTTP_201_CREATED)
async def receive_movement(
    payload: StockMovementCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    if payload.type != "receipt" or not payload.to_warehouse_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Некорректный тип операции")
    await receive_stock(db, payload.to_warehouse_id, payload.part_id, payload.quantity, user.id)
    await db.commit()
    return {"status": "ok"}


@router.post("/movements/transfer", status_code=status.HTTP_201_CREATED)
async def transfer_movement(
    payload: StockMovementCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    if payload.type != "transfer" or not payload.from_warehouse_id or not payload.to_warehouse_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Некорректный тип операции")
    try:
        await transfer_stock(
            db, payload.from_warehouse_id, payload.to_warehouse_id, payload.part_id, payload.quantity, user.id
        )
    except InsufficientStockError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Недостаточно запчастей: доступно {exc.available}, требуется {exc.requested}",
        ) from exc
    await db.commit()
    return {"status": "ok"}


@parts_router.get("", response_model=list[PartOut])
async def list_parts(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(Part).order_by(Part.name))).all()


@parts_router.post("", response_model=PartOut, status_code=status.HTTP_201_CREATED)
async def create_part(
    payload: PartCreate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    part = Part(**payload.model_dump())
    db.add(part)
    await db.commit()
    await db.refresh(part)
    return part
