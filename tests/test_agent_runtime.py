"""H2-1 / H2-2：AgentRuntime.execute_stream 与 execute 聚合。"""
from __future__ import annotations

from typing import AsyncIterator

import pytest

from app.harness.contracts import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    RunContext,
    RunEvent,
    RunRequest,
)
from app.harness.runtime import AgentRuntime


class FakeExecutor:
    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        # sequence 故意乱填，应由 Runtime 覆盖为单调序号
        yield RunEvent(type=RUN_COMPLETED, run_id=ctx.run_id, sequence=999)


class BoomExecutor:
    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        raise ValueError("boom")
        yield  # pragma: no cover — 使类型仍为 AsyncIterator


class NoTerminalExecutor:
    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        yield RunEvent(
            type="model.token",
            run_id=ctx.run_id,
            sequence=0,
            payload={"content": "x"},
        )


class OkExecutor:
    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        yield RunEvent(
            type=RUN_COMPLETED,
            run_id=ctx.run_id,
            sequence=1,
            payload={"output": "你好"},
        )


class TokenThenDoneExecutor:
    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        yield RunEvent(
            type="model.token",
            run_id=ctx.run_id,
            sequence=0,
            payload={"content": "你"},
        )
        yield RunEvent(
            type="model.token",
            run_id=ctx.run_id,
            sequence=1,
            payload={"content": "好"},
        )
        yield RunEvent(type=RUN_COMPLETED, run_id=ctx.run_id, sequence=2, payload={})


@pytest.mark.asyncio
async def test_execute_stream_happy_path_sequence():
    runtime = AgentRuntime(FakeExecutor())
    events = [e async for e in runtime.execute_stream(RunRequest(input="hi"))]

    assert events[0].type == RUN_STARTED
    assert events[0].sequence == 0
    assert events[-1].type == RUN_COMPLETED
    assert [e.sequence for e in events] == list(range(len(events)))
    assert len({e.run_id for e in events}) == 1


@pytest.mark.asyncio
async def test_execute_stream_executor_error_becomes_run_failed():
    runtime = AgentRuntime(BoomExecutor())
    events = [e async for e in runtime.execute_stream(RunRequest(input="hi"))]

    assert events[0].type == RUN_STARTED
    assert events[-1].type == RUN_FAILED
    assert "ValueError" in events[-1].payload["message"]
    assert [e.sequence for e in events] == list(range(len(events)))


@pytest.mark.asyncio
async def test_execute_stream_sequence_resets_across_runs():
    runtime = AgentRuntime(FakeExecutor())
    first = [e async for e in runtime.execute_stream(RunRequest(input="a"))]
    second = [e async for e in runtime.execute_stream(RunRequest(input="b"))]
    assert first[0].sequence == 0
    assert second[0].sequence == 0
    assert first[0].run_id != second[0].run_id


@pytest.mark.asyncio
async def test_execute_stream_fills_missing_terminal():
    runtime = AgentRuntime(NoTerminalExecutor())
    events = [e async for e in runtime.execute_stream(RunRequest(input="hi"))]
    assert [e.type for e in events] == [RUN_STARTED, "model.token", RUN_COMPLETED]
    assert [e.sequence for e in events] == [0, 1, 2]


@pytest.mark.asyncio
async def test_execute_success():
    result = await AgentRuntime(OkExecutor()).execute(RunRequest(input="hi"))
    assert result.status == "succeeded"
    assert result.output == "你好"
    assert result.error is None


@pytest.mark.asyncio
async def test_execute_failed():
    result = await AgentRuntime(BoomExecutor()).execute(RunRequest(input="hi"))
    assert result.status == "failed"
    assert result.error is not None
    assert "ValueError" in result.error["message"]


@pytest.mark.asyncio
async def test_execute_aggregates_tokens_when_completed_has_no_output():
    result = await AgentRuntime(TokenThenDoneExecutor()).execute(
        RunRequest(input="hi")
    )
    assert result.status == "succeeded"
    assert result.output == "你好"
    assert result.metadata.get("run_id")


@pytest.mark.asyncio
async def test_execute_persists_when_session_factory():
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.database import Base
    from app.harness_storage import get_run, list_events

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    result = await AgentRuntime(OkExecutor()).execute(
        RunRequest(
            input="hi",
            agent_id="chat",
            session_id="s1",
            options={"session_factory": factory},
        )
    )

    async with factory() as session:
        row = await get_run(session, result.metadata["run_id"])
        events = await list_events(session, result.metadata["run_id"])

    await engine.dispose()

    assert result.status == "succeeded"
    assert row is not None
    assert row.status == "succeeded"
    assert row.input == "hi"
    assert row.output == "你好"
    assert row.agent_id == "chat"
    assert row.session_id == "s1"
    assert row.ended_at is not None
    assert [e.type for e in events] == [RUN_STARTED, RUN_COMPLETED]
    assert [e.sequence for e in events] == [0, 1]


@pytest.mark.asyncio
async def test_execute_stream_persists_when_session_factory():
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.database import Base
    from app.harness_storage import get_run, list_events

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    req = RunRequest(input="hi", options={"session_factory": factory})
    events = [e async for e in AgentRuntime(OkExecutor()).execute_stream(req)]
    run_id = events[0].run_id

    async with factory() as session:
        row = await get_run(session, run_id)
        rows = await list_events(session, run_id)

    await engine.dispose()

    assert row is not None and row.status == "succeeded"
    assert [e.type for e in events] == [e.type for e in rows]
    assert [e.sequence for e in events] == [e.sequence for e in rows]
