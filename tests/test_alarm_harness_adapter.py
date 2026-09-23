"""H4-3：Alarm HTTP Adapter（mock run_alarm_agent，不打真实流水线）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.harness.adapter.alarm_http import (
    alarm_harness_http,
    to_alarm_response,
    to_run_request,
)
from app.harness.contracts import RunResult


def test_to_run_request_maps_message():
    req = to_run_request("分析告警")
    assert req.input == "分析告警"
    assert req.agent_id == "alarm"
    assert req.caller == "api"


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


@pytest.mark.asyncio
async def test_alarm_harness_http_uses_executor():
    fake = {
        "reply": "ok",
        "intent": "alarm",
        "sources": ["s1"],
        "engine": "alarm",
        "cache_hit": False,
        "skip": False,
        "meta": {},
    }
    with patch(
        "app.agents.harness_alarm.executor.run_alarm_agent",
        new=AsyncMock(return_value=fake),
    ):
        resp = await alarm_harness_http("ping")
    assert resp["reply"] == "ok"
    assert resp["sources"] == ["s1"]
    assert resp["engine"] == "alarm"
