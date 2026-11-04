"""Resolve every printed alias consistently, including guest photos and tickets."""
from sqlalchemy import and_, exists, or_, select
from app.models.core import Equipment
from app.models.qr_label import QRLabel

def equipment_for_token(token):
    label = select(QRLabel.equipment_id).where(QRLabel.token == token).scalar_subquery()
    known = exists(select(QRLabel.token).where(QRLabel.token == token))
    return or_(Equipment.id == label, and_(~known, Equipment.public_qr_token == token))

async def preferred_label(equipment, db):
    return await db.scalar(select(QRLabel).where(QRLabel.equipment_id == equipment.id,
        QRLabel.organization_id == equipment.organization_id)
        .order_by(QRLabel.bound_at.desc().nullslast(), QRLabel.created_at.desc()).limit(1))
