"""H3-4：ToolRunner 校验 / 超时 / 类型化错误。"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.harness.contracts import (
    HarnessError,
    HarnessErrorCategory,
    RunContext,
    RunRequest,
    ToolSpec,
)
from app.harness.registry import ToolRegistry
from app.harness.runtime.cancellation import CancellationToken
from app.harness.tools import ToolRunner


def _ctx() -> RunContext:
    return RunContext(
        run_id="run-1",
        request=RunRequest(input="hi"),
        cancellation_token=CancellationToken(),
    )


def _runner_with(
    name: str,
    handler,
    *,
    required: list[str] | None = None,
    timeout_sec: float = 30.0,
) -> ToolRunner:
    registry = ToolRegistry()
    schema: dict = {"type": "object", "properties": {}}
    if required:
        for key in required:
            schema.setdefault("properties", {})[key] = {"type": "string"}
        schema["required"] = required
    registry.register(
        ToolSpec(
            name=name,
            description="test",
            input_schema=schema,
            timeout_sec=timeout_sec,
        ),
        handler,
    )
    return ToolRunner(registry)


@pytest.mark.asyncio
async def test_arun_success():
    runner = _runner_with("echo", lambda message: f"ok:{message}", required=["message"])
    out = await runner.arun("echo", {"message": "hi"}, _ctx())
    assert out == "ok:hi"


@pytest.mark.asyncio
async def test_unknown_tool_raises_validation():
    runner = ToolRunner(ToolRegistry())
    with pytest.raises(HarnessError) as ei:
        await runner.arun("nope", {}, _ctx())
    assert ei.value.category is HarnessErrorCategory.VALIDATION


@pytest.mark.asyncio
async def test_allowlist_policy():
    called = {"n": 0}

    def handler(message: str) -> str:
        called["n"] += 1
        return message

    runner = _runner_with("echo", handler, required=["message"])
    with pytest.raises(HarnessError) as ei:
        await runner.arun(
            "echo",
            {"message": "x"},
            _ctx(),
            allowlist=["other"],
        )
    assert ei.value.category is HarnessErrorCategory.POLICY
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_missing_required_validation():
    called = {"n": 0}

    def handler(message: str) -> str:
        called["n"] += 1
        return message

    runner = _runner_with("echo", handler, required=["message"])
    with pytest.raises(HarnessError) as ei:
        await runner.arun("echo", {}, _ctx())
    assert ei.value.category is HarnessErrorCategory.VALIDATION
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_timeout():
    def slow() -> str:
        time.sleep(0.2)
        return "late"

    runner = _runner_with("slow", slow, timeout_sec=0.05)
    with pytest.raises(HarnessError) as ei:
        await runner.arun("slow", {}, _ctx())
    assert ei.value.category is HarnessErrorCategory.TIMEOUT


@pytest.mark.asyncio
async def test_tool_error_prefix_becomes_harness_error():
    runner = _runner_with("bad", lambda: "[TOOL_ERROR] boom")
    with pytest.raises(HarnessError) as ei:
        await runner.arun("bad", {}, _ctx())
    assert ei.value.category is HarnessErrorCategory.TOOL
    assert "[TOOL_ERROR]" in ei.value.message


@pytest.mark.asyncio
async def test_async_handler():
    async def ahandler(message: str) -> str:
        await asyncio.sleep(0)
        return message.upper()

    runner = _runner_with("up", ahandler, required=["message"])
    assert await runner.arun("up", {"message": "ab"}, _ctx()) == "AB"
