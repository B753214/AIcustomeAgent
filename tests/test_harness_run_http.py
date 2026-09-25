"""H5-4：Run 回放序列化与组装（SQLite 内存库）。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.harness.adapter.run_http import event_to_dict, run_to_dict
from app.harness.contracts import RUN_COMPLETED, RUN_STARTED, RunEvent
from app.harness_storage import (
    get_run,
    list_events,
    persist_event,
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
async def test_run_replay_assembly(session_factory):
    await persist_run_start(
        session_factory,
        run_id="r-replay",
        input="hi",
        agent_id="chat",
        session_id="s1",
    )
    await persist_event(
        session_factory,
        RunEvent(
            type=RUN_STARTED,
            run_id="r-replay",
            sequence=0,
            payload={},
            timestamp=datetime.now(timezone.utc),
        ),
    )
    await persist_event(
        session_factory,
        RunEvent(
            type=RUN_COMPLETED,
            run_id="r-replay",
            sequence=1,
            payload={"output": "ok"},
            timestamp=datetime.now(timezone.utc),
        ),
    )
    await persist_run_end(
        session_factory,
        "r-replay",
        status="succeeded",
        output="ok",
    )

    async with session_factory() as session:
        row = await get_run(session, "r-replay")
        events = await list_events(session, "r-replay")

    assert row is not None
    body = {
        "run": run_to_dict(row),
        "events": [event_to_dict(e) for e in events],
    }
    assert body["run"]["run_id"] == "r-replay"
    assert body["run"]["status"] == "succeeded"
    assert body["run"]["input"] == "hi"
    assert body["run"]["output"] == "ok"
    assert isinstance(body["run"]["started_at"], str)
    assert isinstance(body["run"]["ended_at"], str)
    assert [e["sequence"] for e in body["events"]] == [0, 1]
    assert [e["type"] for e in body["events"]] == [RUN_STARTED, RUN_COMPLETED]
    assert "run" not in body["events"][0]
    assert body["events"][1]["payload"]["output"] == "ok"


@pytest.mark.asyncio
async def test_run_replay_allows_empty_events(session_factory):
    await persist_run_start(
        session_factory,
        run_id="r-empty",
        input="x",
    )
    async with session_factory() as session:
        row = await get_run(session, "r-empty")
        events = await list_events(session, "r-empty")

    assert row is not None
    assert events == []
    assert run_to_dict(row)["status"] == "running"
