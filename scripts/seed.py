"""Наполняет пустую БД минимальным набором данных для ручного теста API.

Создаёт: admin, техника (с его мобильным складом), центральный склад,
один тип и одну единицу оборудования, одну запчасть с остатком на
центральном складе. Безопасно перезапускать — уже существующие по email/
серийнику записи пропускаются.
"""
import asyncio
import os

from sqlalchemy import select

from app.core.security import hash_password
from app.database import AsyncSessionLocal
from app.models.core import Equipment, EquipmentType, User, UserRole
from app.models.customer import Client, Site
from app.models.organization import Organization, OrganizationMembership
from app.models.warehouse import Part, Warehouse, WarehouseStock, WarehouseType

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = os.getenv("INITIAL_ADMIN_PASSWORD", "admin12345")
TECH_EMAIL = "tech@example.com"
TECH_PASSWORD = os.getenv("INITIAL_TECH_PASSWORD", "tech12345")


async def main() -> None:
    async with AsyncSessionLocal() as db:
        organization = await db.scalar(select(Organization).where(Organization.slug == "fixit-default"))
        if not organization:
            organization = Organization(name="Fixit Default", slug="fixit-default")
            db.add(organization)
            await db.flush()
        admin = await db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        if not admin:
            admin = User(
                full_name="Администратор",
                email=ADMIN_EMAIL,
                role=UserRole.admin,
                hashed_password=hash_password(ADMIN_PASSWORD),
            )
            db.add(admin)

        technician = await db.scalar(select(User).where(User.email == TECH_EMAIL))
        if not technician:
            technician = User(
                full_name="Иванов Алексей",
                email=TECH_EMAIL,
                role=UserRole.technician,
                hashed_password=hash_password(TECH_PASSWORD),
            )
            db.add(technician)
        await db.flush()  # получаем technician.id для мобильного склада ниже

        for user, role in ((admin, UserRole.owner), (technician, UserRole.technician)):
            membership = await db.scalar(select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization.id,
                OrganizationMembership.user_id == user.id,
            ))
            if not membership:
                db.add(OrganizationMembership(
                    organization_id=organization.id, user_id=user.id, role=role,
                ))

        central = await db.scalar(select(Warehouse).where(
            Warehouse.organization_id == organization.id, Warehouse.type == WarehouseType.central
        ))
        if not central:
            central = Warehouse(organization_id=organization.id, type=WarehouseType.central, name="Центральный склад")
            db.add(central)

        mobile = await db.scalar(select(Warehouse).where(
            Warehouse.organization_id == organization.id,
            Warehouse.owner_user_id == technician.id,
        ))
        if not mobile:
            mobile = Warehouse(organization_id=organization.id, type=WarehouseType.mobile,
                               name="Склад техника (авто)", owner_user_id=technician.id)
            db.add(mobile)

        eq_type = await db.scalar(select(EquipmentType).where(
            EquipmentType.organization_id == organization.id, EquipmentType.name == "Поломоечная машина"
        ))
        if not eq_type:
            eq_type = EquipmentType(organization_id=organization.id, name="Поломоечная машина")
            db.add(eq_type)
        await db.flush()

        client = await db.scalar(select(Client).where(
            Client.organization_id == organization.id, Client.name == "Демо-клиент",
        ))
        if not client:
            client = Client(organization_id=organization.id, name="Демо-клиент")
            db.add(client)
            await db.flush()
        site = await db.scalar(select(Site).where(
            Site.organization_id == organization.id,
            Site.client_id == client.id,
            Site.name == "Склад «Северный», уч. 4",
        ))
        if not site:
            site = Site(
                organization_id=organization.id,
                client_id=client.id,
                name="Склад «Северный», уч. 4",
                address="Склад «Северный», участок 4",
            )
            db.add(site)
            await db.flush()

        equipment = await db.scalar(select(Equipment).where(
            Equipment.organization_id == organization.id,
            Equipment.serial_number == "KB-2201-4471",
        ))
        if not equipment:
            equipment = Equipment(
                organization_id=organization.id,
                site_id=site.id,
                equipment_type_id=eq_type.id,
                name="Поломоечная машина",
                manufacturer="Kärcher",
                model="BD 50/70",
                serial_number="KB-2201-4471",
                location="Склад «Северный», уч. 4",
            )
            db.add(equipment)

        part = await db.scalar(select(Part).where(
            Part.organization_id == organization.id,
            Part.article == "KB-PUMP-70",
        ))
        if not part:
            part = Part(organization_id=organization.id, article="KB-PUMP-70",
                        name="Насос подачи воды", min_critical_qty=1)
            db.add(part)
        await db.flush()

        stock = await db.get(WarehouseStock, {"warehouse_id": central.id, "part_id": part.id})
        if not stock:
            db.add(WarehouseStock(warehouse_id=central.id, part_id=part.id, quantity=10))

        await db.commit()

    print("Готово. Учётные данные для входа:")
    print(f"  admin:      {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    print(f"  technician: {TECH_EMAIL} / {TECH_PASSWORD}")
    print(f"  оборудование: серийный номер KB-2201-4471, QR откроется по /api/equipment/{{id}}/qr")


if __name__ == "__main__":
    asyncio.run(main())
