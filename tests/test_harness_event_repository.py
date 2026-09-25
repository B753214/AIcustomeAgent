"""H5-4：HarnessRunEvent 仓储（SQLite 内存库）。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.harness.contracts import RUN_COMPLETED, RUN_STARTED, RunEvent
from app.harness_storage import append_event, list_events


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
async def test_append_and_list_ordered(db_session: AsyncSession):
    e0 = RunEvent(
        type=RUN_STARTED,
        run_id="r-1",
        sequence=0,
        payload={},
        timestamp=datetime.now(timezone.utc),
    )
    e1 = RunEvent(
        type=RUN_COMPLETED,
        run_id="r-1",
        sequence=1,
        payload={"output": "ok"},
        timestamp=datetime.now(timezone.utc),
    )
    row0 = await append_event(db_session, e0)
    row1 = await append_event(db_session, e1)
    assert row0 is not None and row0.type == RUN_STARTED
    assert row1 is not None and row1.payload["output"] == "ok"

    rows = await list_events(db_session, "r-1")
    assert [r.sequence for r in rows] == [0, 1]
    assert [r.type for r in rows] == [RUN_STARTED, RUN_COMPLETED]


@pytest.mark.asyncio
async def test_append_skips_internal(db_session: AsyncSession):
    ev = RunEvent(
        type="debug.trace",
        run_id="r-2",
        sequence=0,
        payload={"x": 1},
        visibility="internal",
    )
    assert await append_event(db_session, ev) is None
    assert await list_events(db_session, "r-2") == []
