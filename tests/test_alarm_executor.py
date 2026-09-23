"""H4-3：AlarmExecutor（mock run_alarm_agent，不打真实告警流水线）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.harness_alarm.executor import AlarmExecutor
from app.harness.contracts import RUN_COMPLETED, RUN_FAILED, RunContext, RunRequest


@pytest.mark.asyncio
async def test_alarm_executor_maps_run_result():
    fake = {
        "reply": "告警分析完成",
        "intent": "alarm",
        "sources": ["mon#1"],
        "engine": "alarm",
        "cache_hit": False,
        "skip": False,
        "meta": {"page_count": 1},
    }
    with patch(
        "app.agents.harness_alarm.executor.run_alarm_agent",
        new=AsyncMock(return_value=fake),
    ) as mocked:
        ctx = RunContext(
            run_id="r1",
            request=RunRequest(input="分析这条告警", agent_id="alarm"),
        )
        events = [ev async for ev in AlarmExecutor().astream(ctx)]

    assert len(events) == 1
    ev = events[0]
    assert ev.type == RUN_COMPLETED
    assert ev.payload["output"] == "告警分析完成"
    assert ev.payload["sources"] == ["mon#1"]
    assert ev.payload["metadata"]["intent"] == "alarm"
    assert ev.payload["metadata"]["engine"] == "alarm"
    assert ev.payload["metadata"]["page_count"] == 1
    mocked.assert_awaited_once_with("分析这条告警")


@pytest.mark.asyncio
async def test_alarm_executor_yields_run_failed_on_error():
    with patch(
        "app.agents.harness_alarm.executor.run_alarm_agent",
        new=AsyncMock(side_effect=RuntimeError("pipeline down")),
    ):
        ctx = RunContext(
            run_id="r2",
            request=RunRequest(input="x", agent_id="alarm"),
        )
        events = [ev async for ev in AlarmExecutor().astream(ctx)]

    assert len(events) == 1
    assert events[0].type == RUN_FAILED
    assert events[0].payload["message"] == "pipeline down"
