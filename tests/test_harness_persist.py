"""H5-4：短事务 persist helper（SQLite 内存库）。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.harness.contracts import RUN_COMPLETED, RUN_STARTED, RunEvent
from app.agents.harness_alarm.checkpoint import ALARM_AFTER_FETCH
from app.harness_storage import (
    get_run,
    list_events,
    persist_checkpoint,
    persist_event,
    persist_load_checkpoint,
    persist_run_end,
    persist_run_start,
)


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_persist_run_and_events_ordered(session_factory):
    await persist_run_start(
        session_factory,
        run_id="r-1",
        input="hi",
        agent_id="chat",
        session_id="s1",
    )
    await persist_event(
        session_factory,
        RunEvent(
            type=RUN_STARTED,
            run_id="r-1",
            sequence=0,
            payload={},
            timestamp=datetime.now(timezone.utc),
        ),
    )
    await persist_event(
        session_factory,
        RunEvent(
            type=RUN_COMPLETED,
            run_id="r-1",
            sequence=1,
            payload={"output": "ok"},
            timestamp=datetime.now(timezone.utc),
        ),
    )
    await persist_run_end(
        session_factory,
        "r-1",
        status="succeeded",
        output="ok",
    )

    async with session_factory() as session:
        row = await get_run(session, "r-1")
        events = await list_events(session, "r-1")

    assert row is not None
    assert row.status == "succeeded"
    assert row.input == "hi"
    assert row.output == "ok"
    assert row.agent_id == "chat"
    assert row.session_id == "s1"
    assert [e.sequence for e in events] == [0, 1]
    assert [e.type for e in events] == [RUN_STARTED, RUN_COMPLETED]


@pytest.mark.asyncio
async def test_persist_event_skips_internal(session_factory):
    await persist_event(
        session_factory,
        RunEvent(
            type="debug.trace",
            run_id="r-2",
            sequence=0,
            payload={"x": 1},
            visibility="internal",
        ),
    )
    async with session_factory() as session:
        assert await list_events(session, "r-2") == []


@pytest.mark.asyncio
async def test_persist_noop_when_factory_none():
    await persist_run_start(None, run_id="r-3", input="x")
    await persist_event(
        None,
        RunEvent(type=RUN_STARTED, run_id="r-3", sequence=0, payload={}),
    )
    await persist_run_end(None, "r-3", status="succeeded")
    await persist_checkpoint(None, "r-3", ALARM_AFTER_FETCH, {"pages": 1})
    assert await persist_load_checkpoint(None, "r-3", ALARM_AFTER_FETCH) is None


@pytest.mark.asyncio
async def test_persist_checkpoint_save_load_overwrite(session_factory):
    await persist_checkpoint(
        session_factory,
        "r-cp",
        ALARM_AFTER_FETCH,
        {"pages": 1, "idempotency_keys": ["fetch:1"]},
    )
    loaded = await persist_load_checkpoint(
        session_factory, "r-cp", ALARM_AFTER_FETCH
    )
    assert loaded == {"pages": 1, "idempotency_keys": ["fetch:1"]}

    await persist_checkpoint(
        session_factory,
        "r-cp",
        ALARM_AFTER_FETCH,
        {"pages": 2, "idempotency_keys": ["fetch:1", "fetch:2"]},
    )
    loaded2 = await persist_load_checkpoint(
        session_factory, "r-cp", ALARM_AFTER_FETCH
    )
    assert loaded2 is not None
    assert loaded2["pages"] == 2
    assert loaded2["idempotency_keys"] == ["fetch:1", "fetch:2"]


@pytest.mark.asyncio
async def test_persist_load_checkpoint_missing(session_factory):
    assert (
        await persist_load_checkpoint(session_factory, "r-x", ALARM_AFTER_FETCH)
        is None
    )
