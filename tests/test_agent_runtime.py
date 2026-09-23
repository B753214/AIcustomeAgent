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
