"""H5-2：HarnessCheckpoint 仓储（SQLite 内存库）。"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.harness_storage import (
    list_checkpoints,
    load_checkpoint,
    save_checkpoint,
)


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
        await session.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_save_load_overwrite_list(db_session: AsyncSession):
    saved = await save_checkpoint(
        db_session,
        "r-1",
        "alarm.after_fetch",
        {"pages": 1, "playbook": "default"},
    )
    assert saved.run_id == "r-1"
    assert saved.name == "alarm.after_fetch"
    assert saved.payload["pages"] == 1

    loaded = await load_checkpoint(db_session, "r-1", "alarm.after_fetch")
    assert loaded is not None
    assert loaded.payload == {"pages": 1, "playbook": "default"}

    await save_checkpoint(
        db_session,
        "r-1",
        "alarm.after_fetch",
        {"pages": 2, "playbook": "default"},
    )
    loaded2 = await load_checkpoint(db_session, "r-1", "alarm.after_fetch")
    assert loaded2 is not None
    assert loaded2.payload["pages"] == 2

    await save_checkpoint(
        db_session,
        "r-1",
        "alarm.after_analyze",
        {"summary": "ok"},
    )
    items = await list_checkpoints(db_session, "r-1")
    assert len(items) == 2
    names = {c.name for c in items}
    assert names == {"alarm.after_fetch", "alarm.after_analyze"}


@pytest.mark.asyncio
async def test_load_missing_returns_none(db_session: AsyncSession):
    assert await load_checkpoint(db_session, "r-x", "nope") is None
