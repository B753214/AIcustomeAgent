from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from AICustomeRobort.app.config import get_settings, settings
from AICustomeRobort.app.models.sessions import ChatSession, ChatMessage
engine = create_async_engine(settings.POSTGRES_URI, echo=settings.DEBUG, pool_pre_ping=True)
AsyncSession = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class Base(DeclarativeBase):
    pass

async def get_db()->AsyncGenerator[AsyncSession, None]:
    async with AsyncSession() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            raise e
        finally:
            await session.close()

async def init_db()->None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        print("Database initialized")
