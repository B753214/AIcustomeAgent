"""H4-3：AlarmExecutor（mock run_alarm_agent_stream）。"""
from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.harness_alarm.executor import AlarmExecutor
from app.harness.contracts import (
    MODEL_TOKEN,
    RUN_COMPLETED,
    RUN_FAILED,
    WORKFLOW_STEP,
    RunContext,
    RunRequest,
)


async def _fake_stream(*_args: Any, **_kwargs: Any) -> AsyncIterator[dict]:
    yield {"type": "stage", "stage": "alarm_fetch", "msg": "拉取中", "ok": True}
    yield {"type": "token", "content": "告"}
    yield {"type": "token", "content": "警"}
    yield {
        "type": "done",
        "reply": "告警分析完成",
        "intent": "alarm",
        "sources": ["mon#1"],
        "engine": "alarm",
        "cache_hit": False,
        "skip": False,
        "meta": {"page_count": 1},
    }


@pytest.mark.asyncio
async def test_alarm_executor_maps_stream_chunks():
    with (
        patch(
            "app.agents.harness_alarm.executor.run_alarm_agent_stream",
            new=_fake_stream,
        ),
        patch(
            "app.agents.harness_alarm.executor.persist_load_checkpoint",
            new=AsyncMock(return_value=None),
        ),
    ):
        ctx = RunContext(
            run_id="r1",
            request=RunRequest(input="分析这条告警", agent_id="alarm"),
        )
        events = [ev async for ev in AlarmExecutor().astream(ctx)]

    assert [e.type for e in events] == [
        WORKFLOW_STEP,
        MODEL_TOKEN,
        MODEL_TOKEN,
        RUN_COMPLETED,
    ]
    assert events[0].payload["message"] == "拉取中"
    assert events[1].payload["content"] == "告"
    done = events[-1]
    assert done.payload["output"] == "告警分析完成"
    assert done.payload["sources"] == ["mon#1"]
    assert done.payload["metadata"]["page_count"] == 1
    assert done.payload["metadata"]["engine"] == "alarm"


@pytest.mark.asyncio
async def test_alarm_executor_yields_run_failed_on_error():
    async def boom(*_a, **_k):
        raise RuntimeError("pipeline down")
        yield  # pragma: no cover

    with (
        patch(
            "app.agents.harness_alarm.executor.run_alarm_agent_stream",
            new=boom,
        ),
        patch(
            "app.agents.harness_alarm.executor.persist_load_checkpoint",
            new=AsyncMock(return_value=None),
        ),
    ):
        ctx = RunContext(
            run_id="r2",
            request=RunRequest(input="x", agent_id="alarm"),
        )
        events = [ev async for ev in AlarmExecutor().astream(ctx)]

    assert len(events) == 1
    assert events[0].type == RUN_FAILED
    assert events[0].payload["message"] == "pipeline down"
