"""H2-4：CancellationToken 与 Runtime 取消行为。"""
from __future__ import annotations

import asyncio
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
from app.harness.runtime.cancellation import CancellationToken


def test_cancellation_token_basic():
    token = CancellationToken()
    assert token.is_cancelled() is False
    token.cancel()
    assert token.is_cancelled() is True


@pytest.mark.asyncio
async def test_cancellation_token_wait():
    token = CancellationToken()

    async def cancel_soon() -> None:
        await asyncio.sleep(0.01)
        token.cancel()

    asyncio.create_task(cancel_soon())
    await asyncio.wait_for(token.wait(), timeout=1.0)
    assert token.is_cancelled() is True


class SlowExecutor:
    """先发一条业务事件，sleep 后再发第二条；供测试中途 cancel。"""

    def __init__(self) -> None:
        self.seen_tokens: list[CancellationToken] = []

    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        assert ctx.cancellation_token is not None
        self.seen_tokens.append(ctx.cancellation_token)
        yield RunEvent(
            type="model.token",
            run_id=ctx.run_id,
            sequence=1,
            payload={"content": "A"},
        )
        await asyncio.sleep(0.05)
        if ctx.cancellation_token.is_cancelled():
            return
        yield RunEvent(
            type="model.token",
            run_id=ctx.run_id,
            sequence=2,
            payload={"content": "B"},
        )
        yield RunEvent(type=RUN_COMPLETED, run_id=ctx.run_id, sequence=3, payload={})


@pytest.mark.asyncio
async def test_execute_stream_stops_after_cancel():
    executor = SlowExecutor()
    runtime = AgentRuntime(executor)
    stream = runtime.execute_stream(RunRequest(input="hi"))

    first = await stream.__anext__()
    assert first.type == RUN_STARTED

    second = await stream.__anext__()
    assert second.type == "model.token"
    assert second.payload["content"] == "A"

    # 中途取消：不应再出现 content=B
    assert executor.seen_tokens
    executor.seen_tokens[0].cancel()

    rest = [ev async for ev in stream]
    types = [ev.type for ev in rest]
    contents = [
        ev.payload.get("content")
        for ev in rest
        if ev.type == "model.token"
    ]

    assert "B" not in contents
    assert RUN_FAILED in types or RUN_COMPLETED not in types
    # Runtime 在取消后应给出失败终态（带 cancelled 标记）
    failed = [ev for ev in rest if ev.type == RUN_FAILED]
    assert failed
    assert failed[-1].payload.get("cancelled") is True


@pytest.mark.asyncio
async def test_execute_maps_cancel_to_cancelled_status():
    class CancelSelfExecutor:
        async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
            yield RunEvent(
                type="model.token",
                run_id=ctx.run_id,
                sequence=1,
                payload={"content": "x"},
            )
            assert ctx.cancellation_token is not None
            ctx.cancellation_token.cancel()
            # 下一条在 Runtime 检查取消后不应被转发
            yield RunEvent(
                type="model.token",
                run_id=ctx.run_id,
                sequence=2,
                payload={"content": "y"},
            )

    result = await AgentRuntime(CancelSelfExecutor()).execute(RunRequest(input="hi"))
    assert result.status == "cancelled"
    assert result.error is not None
    assert result.error.get("cancelled") is True
