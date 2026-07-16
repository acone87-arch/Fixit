"""Локальный dev-бутстрап: создаёт все таблицы напрямую из моделей.

Для реального проекта источник правды — Alembic-миграции (см. README).
Этот скрипт — только чтобы быстро обкатать API без настройки Alembic.
"""
import asyncio

from app.database import Base, engine
from app import models  # noqa: F401 — импорт регистрирует все модели в Base.metadata


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Таблицы созданы.")


if __name__ == "__main__":
    asyncio.run(main())
