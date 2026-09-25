"""H5-1：HarnessRun 仓储（SQLite 内存库，不依赖外部 PG）。"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.harness_storage import create_run, get_run, update_run
from app.harness_storage.models import HarnessRun


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
async def test_create_update_get_run(db_session: AsyncSession):
    run = await create_run(
        db_session,
        run_id="r-1",
        input="你好",
        agent_id="chat",
        session_id="s-1",
    )
    assert run.run_id == "r-1"
    assert run.status == "running"
    assert run.input == "你好"
    assert isinstance(run, HarnessRun)

    updated = await update_run(
        db_session,
        "r-1",
        status="succeeded",
        output="hello",
        usage={"tokens": 3},
    )
    assert updated is not None
    assert updated.status == "succeeded"
    assert updated.output == "hello"
    assert updated.usage == {"tokens": 3}
    assert updated.ended_at is not None

    got = await get_run(db_session, "r-1")
    assert got is not None
    assert got.status == "succeeded"
    assert got.agent_id == "chat"


@pytest.mark.asyncio
async def test_update_missing_run_returns_none(db_session: AsyncSession):
    assert await update_run(db_session, "missing", status="failed") is None
