"""H4-3：Alarm HTTP Adapter（mock stream，不打真实流水线）。"""
from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest

from app.harness.adapter.alarm_http import (
    alarm_event_to_sse_dict,
    alarm_harness_http,
    alarm_harness_stream,
    to_alarm_response,
    to_run_request,
)
from app.harness.contracts import (
    MODEL_TOKEN,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    WORKFLOW_STEP,
    RunEvent,
    RunResult,
)


def test_to_run_request_maps_message():
    req = to_run_request("分析告警")
    assert req.input == "分析告警"
    assert req.agent_id == "alarm"
    assert req.caller == "api"
    assert req.options.get("session_factory") is not None


def test_to_alarm_response_maps_result():
    result = RunResult(
        status="succeeded",
        output="报告正文",
        sources=["mon#1"],
        metadata={"intent": "alarm", "engine": "alarm"},
    )
    resp = to_alarm_response(result)
    assert resp["reply"] == "报告正文"
    assert resp["sources"] == ["mon#1"]
    assert resp["intent"] == "alarm"
    assert resp["engine"] == "alarm"


def test_alarm_event_to_sse_dict_mapping():
    assert (
        alarm_event_to_sse_dict(
            RunEvent(type=RUN_STARTED, run_id="r", sequence=0, payload={})
        )
        is None
    )
    assert alarm_event_to_sse_dict(
        RunEvent(
            type=MODEL_TOKEN,
            run_id="r",
            sequence=1,
            payload={"content": "x"},
        )
    ) == {"type": "chunk", "content": "x"}
    assert alarm_event_to_sse_dict(
        RunEvent(
            type=WORKFLOW_STEP,
            run_id="r",
            sequence=2,
            payload={"message": "拉取中"},
        )
    ) == {"type": "progress", "message": "拉取中"}
    assert alarm_event_to_sse_dict(
        RunEvent(
            type=RUN_COMPLETED,
            run_id="r",
            sequence=3,
            payload={
                "output": "报告",
                "metadata": {"skip": True, "page_count": 1},
            },
        )
    ) == {
        "type": "done",
        "run_id": "r",
        "report": "报告",
        "meta": {"page_count": 1},
        "skip": True,
    }
    assert alarm_event_to_sse_dict(
        RunEvent(
            type=RUN_FAILED,
            run_id="r",
            sequence=4,
            payload={"message": "boom"},
        )
    ) == {"type": "error", "run_id": "r", "message": "boom"}


async def _fake_stream(*_args: Any, **_kwargs: Any) -> AsyncIterator[dict]:
    yield {"type": "stage", "stage": "alarm_fetch", "msg": "拉取中", "ok": True}
    yield {"type": "token", "content": "ok"}
    yield {
        "type": "done",
        "reply": "ok",
        "intent": "alarm",
        "sources": ["s1"],
        "engine": "alarm",
        "cache_hit": False,
        "skip": False,
        "meta": {},
    }


@pytest.mark.asyncio
async def test_alarm_harness_http_uses_executor():
    with (
        patch(
            "app.agents.harness_alarm.executor.run_alarm_agent_stream",
            new=_fake_stream,
        ),
        patch(
            "app.agents.harness_alarm.executor.persist_load_checkpoint",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.agents.harness_alarm.executor.persist_checkpoint",
            new=AsyncMock(),
        ),
        patch("app.harness.runtime.agent_runtime.persist_run_start", new=AsyncMock()),
        patch("app.harness.runtime.agent_runtime.persist_event", new=AsyncMock()),
        patch("app.harness.runtime.agent_runtime.persist_run_end", new=AsyncMock()),
    ):
        resp = await alarm_harness_http("ping")
    assert resp["reply"] == "ok"
    assert resp["sources"] == ["s1"]
    assert resp["engine"] == "alarm"


@pytest.mark.asyncio
async def test_alarm_harness_stream_yields_analyze_chunks():
    with (
        patch(
            "app.agents.harness_alarm.executor.run_alarm_agent_stream",
            new=_fake_stream,
        ),
        patch(
            "app.agents.harness_alarm.executor.persist_load_checkpoint",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.agents.harness_alarm.executor.persist_checkpoint",
            new=AsyncMock(),
        ),
        patch("app.harness.runtime.agent_runtime.persist_run_start", new=AsyncMock()),
        patch("app.harness.runtime.agent_runtime.persist_event", new=AsyncMock()),
        patch("app.harness.runtime.agent_runtime.persist_run_end", new=AsyncMock()),
    ):
        frames = [f async for f in alarm_harness_stream("ping")]

    assert frames[0] == {"type": "progress", "message": "拉取中"}
    assert frames[1] == {"type": "chunk", "content": "ok"}
    assert frames[2]["type"] == "done"
    assert frames[2]["report"] == "ok"
    assert frames[2]["run_id"]
