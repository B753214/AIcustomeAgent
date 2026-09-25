"""H7-1 Failure 注入：模型/调用超时、工具失败 → 标准 run.failed。"""
from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

import pytest

from app.harness.contracts import (
    RUN_FAILED,
    RUN_STARTED,
    HarnessError,
    HarnessErrorCategory,
    RunContext,
    RunEvent,
    RunRequest,
    ToolSpec,
)
from app.harness.registry import ToolRegistry
from app.harness.runtime import AgentRuntime
from app.harness.runtime.cancellation import CancellationToken
from app.harness.tools import ToolRunner


class TimeoutExecutor:
    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        raise TimeoutError("model call timed out")
        yield  # pragma: no cover


class AsyncioTimeoutExecutor:
    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        raise asyncio.TimeoutError()
        yield  # pragma: no cover


class ToolFailExecutor:
    """Executor 内调 ToolRunner，工具返回 [TOOL_ERROR] → 冒泡为 run.failed。"""

    def __init__(self) -> None:
        reg = ToolRegistry()
        reg.register(
            ToolSpec(
                name="bad_tool",
                description="always fails",
                input_schema={"type": "object", "properties": {}},
            ),
            lambda: "[TOOL_ERROR] upstream down",
        )
        self._runner = ToolRunner(reg)

    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        await self._runner.arun("bad_tool", {}, ctx)
        yield  # pragma: no cover


@pytest.mark.asyncio
async def test_runtime_maps_timeout_error_to_run_failed():
    runtime = AgentRuntime(TimeoutExecutor())
    events = [e async for e in runtime.execute_stream(RunRequest(input="hi"))]

    assert events[0].type == RUN_STARTED
    assert events[-1].type == RUN_FAILED
    assert events[-1].payload["category"] == HarnessErrorCategory.TIMEOUT.value
    assert "timed out" in events[-1].payload["message"].lower() or "Timeout" in (
        events[-1].payload.get("details") or {}
    ).get("original_type", "")


@pytest.mark.asyncio
async def test_runtime_maps_asyncio_timeout_to_run_failed():
    runtime = AgentRuntime(AsyncioTimeoutExecutor())
    events = [e async for e in runtime.execute_stream(RunRequest(input="hi"))]

    assert events[-1].type == RUN_FAILED
    assert events[-1].payload["category"] == HarnessErrorCategory.TIMEOUT.value


@pytest.mark.asyncio
async def test_runtime_tool_failure_becomes_run_failed():
    runtime = AgentRuntime(ToolFailExecutor())
    events = [
        e
        async for e in runtime.execute_stream(
            RunRequest(
                input="hi",
                options={"cancellation_token": CancellationToken()},
            )
        )
    ]

    assert events[0].type == RUN_STARTED
    assert events[-1].type == RUN_FAILED
    assert events[-1].payload["category"] == HarnessErrorCategory.TOOL.value
    assert "TOOL_ERROR" in events[-1].payload["message"]


@pytest.mark.asyncio
async def test_tool_runner_timeout_is_harness_timeout():
    """与 test_tool_runner 互补：明确 Failure 层入口。"""
    reg = ToolRegistry()

    def slow() -> str:
        time.sleep(0.2)
        return "late"

    reg.register(
        ToolSpec(
            name="slow",
            description="slow",
            timeout_sec=0.05,
        ),
        slow,
    )
    with pytest.raises(HarnessError) as ei:
        await ToolRunner(reg).arun(
            "slow",
            {},
            RunContext(
                run_id="r",
                request=RunRequest(input="x"),
                cancellation_token=CancellationToken(),
            ),
        )
    assert ei.value.category is HarnessErrorCategory.TIMEOUT
