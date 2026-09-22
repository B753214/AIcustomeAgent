"""H1-T：Harness contracts 构造 / 校验 / 事件常量单测（不接 Runtime）。"""
from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

import pytest
from pydantic import ValidationError

from app.harness.contracts import (
    EVENT_TYPES,
    MODEL_TOKEN,
    RUN_COMPLETED,
    RUN_STARTED,
    TOOL_STARTED,
    AgentExecutor,
    HarnessError,
    HarnessErrorCategory,
    RunContext,
    RunEvent,
    RunRequest,
    RunResult,
    ToolSpec,
)


def test_run_request_requires_non_empty_input():
    with pytest.raises(ValidationError):
        RunRequest(input="")
    req = RunRequest(input="你好", agent_id="chat")
    assert req.caller == "api"
    assert req.agent_id == "chat"
    assert req.options == {}
    assert req.model_dump()["input"] == "你好"


def test_run_request_rejects_missing_input():
    with pytest.raises(ValidationError):
        RunRequest()  # type: ignore[call-arg]


def test_run_context_embeds_request():
    req = RunRequest(input="hi", session_id="s1")
    ctx = RunContext(run_id="run-1", request=req)
    assert ctx.trace_id is None
    assert ctx.messages == []
    assert ctx.budget == {}
    assert ctx.request.session_id == "s1"


def test_run_event_and_event_types():
    required = {
        "run.started",
        "route.selected",
        "model.started",
        "model.token",
        "model.completed",
        "tool.started",
        "tool.completed",
        "tool.failed",
        "workflow.step",
        "run.completed",
        "run.failed",
    }
    assert required.issubset(set(EVENT_TYPES))
    assert len(EVENT_TYPES) == 11

    ev = RunEvent(type=RUN_STARTED, run_id="r1", sequence=0, payload={"ok": True})
    assert ev.visibility == "public"
    assert isinstance(ev.timestamp, datetime)
    assert ev.timestamp.tzinfo is not None

    with pytest.raises(ValidationError):
        RunEvent(type=RUN_STARTED, run_id="r1", sequence=-1)


def test_run_result_status_and_mapping_fields():
    ok = RunResult(status="succeeded", output="回复", metadata={"intent": "chat"})
    assert ok.error is None
    assert ok.sources == []

    err = RunResult(
        status="failed",
        error={"category": "timeout", "message": "deadline"},
    )
    assert err.status == "failed"

    with pytest.raises(ValidationError):
        RunResult(status="error")  # 旧词表不允许


def test_tool_spec_query_order_shape():
    spec = ToolSpec(
        name="query_order",
        description="查询订单状态与物流（Mock）",
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
        },
        timeout_sec=30,
        idempotent=True,
    )
    assert spec.version == "1.0"
    assert spec.retry == 0
    dumped = spec.model_dump()
    assert dumped["name"] == "query_order"
    assert dumped["idempotent"] is True


def test_harness_error_to_dict_and_from_exception():
    err = HarnessError(
        HarnessErrorCategory.TOOL,
        "订单查询失败",
        details={"tool": "query_order"},
    )
    d = err.to_dict()
    assert d == {
        "category": "tool",
        "message": "订单查询失败",
        "details": {"tool": "query_order"},
    }

    wrapped = HarnessError.from_exception(
        ValueError("boom"),
        category=HarnessErrorCategory.MODEL,
    )
    assert wrapped.category is HarnessErrorCategory.MODEL
    assert "ValueError" in wrapped.message
    assert wrapped.details["original_type"] == "ValueError"

    same = HarnessError.from_exception(err)
    assert same is err


@pytest.mark.asyncio
async def test_agent_executor_protocol_with_fake():
    class FakeExecutor:
        async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
            yield RunEvent(type=RUN_STARTED, run_id=ctx.run_id, sequence=0)
            yield RunEvent(
                type=TOOL_STARTED,
                run_id=ctx.run_id,
                sequence=1,
                payload={"tool": "query_order"},
            )
            yield RunEvent(
                type=RUN_COMPLETED,
                run_id=ctx.run_id,
                sequence=2,
                payload={"status": "succeeded", "output": "ok"},
            )

    fake: AgentExecutor = FakeExecutor()
    ctx = RunContext(run_id="r-fake", request=RunRequest(input="查订单"))
    events = [ev async for ev in fake.astream(ctx)]
    assert [e.type for e in events] == [RUN_STARTED, TOOL_STARTED, RUN_COMPLETED]
    assert events[-1].payload["output"] == "ok"


def test_model_token_constant_usable_in_event():
    ev = RunEvent(
        type=MODEL_TOKEN,
        run_id="r1",
        sequence=3,
        payload={"content": "你"},
        visibility="public",
    )
    assert ev.type == "model.token"
