from collections.abc import AsyncGenerator
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    # Каждый Mapped[datetime] по умолчанию становится TIMESTAMP WITH TIME ZONE,
    # а не "наивным" TIMESTAMP. Без этого запись значений, пришедших из браузера
    # (JS Date().toISOString() всегда с указанием часового пояса), падает с
    # ошибкой asyncpg "can't subtract offset-naive and offset-aware datetimes".
    type_annotation_map = {datetime: DateTime(timezone=True)}


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
