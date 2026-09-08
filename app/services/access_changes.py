"""Сериализация выдачи/отзыва прав в tenant; operational workflow не блокируется."""
from fastapi import HTTPException
from sqlalchemy import select

from app.models.core import User
from app.models.organization import Organization, OrganizationMembership


async def lock_access_changes(db, organization_id, actor=None):
    organization = await db.scalar(select(Organization).where(
        Organization.id == organization_id).with_for_update().execution_options(populate_existing=True))
    if not organization or not organization.is_active:
        raise HTTPException(403, "Организация отключена")
    if actor is not None:
        # Authentication могла выполниться до ожидания блокировки и отзыва.
        member = await db.scalar(select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == actor.id,
        ).execution_options(populate_existing=True))
        account = await db.scalar(select(User).where(User.id == actor.id).execution_options(populate_existing=True))
        if not member or not member.is_active or not account or not account.is_active:
            raise HTTPException(403, "Доступ отозван")
    return organization
