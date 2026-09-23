"""H4-4：Router（mock 分类依赖，不打真实 LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.harness.routing import RouteDecision, classify
from app.harness.routing.router import _to_agent_id
from app.services.chat import IntentEnum


def test_to_agent_id_mapping():
    assert _to_agent_id(IntentEnum.ALARM) == "alarm"
    assert _to_agent_id(IntentEnum.KNOWLEDGE) == "knowledge"
    assert _to_agent_id(IntentEnum.CHAT) == "chat"
    assert _to_agent_id(IntentEnum.ORDER) == "chat"
    assert _to_agent_id(IntentEnum.UNKNOWN) == "chat"
    assert _to_agent_id("knowledge") == "knowledge"


@pytest.mark.asyncio
async def test_classify_skips_when_agent_id_preset():
    with (
        patch("app.harness.routing.router.is_alarm_message") as alarm_mock,
        patch(
            "app.harness.routing.router.classify_intent",
            new=AsyncMock(),
        ) as intent_mock,
    ):
        decision = await classify("任意内容", agent_id="knowledge")

    assert decision == RouteDecision(
        agent_id="knowledge",
        reason="preset",
        confidence=1.0,
    )
    alarm_mock.assert_not_called()
    intent_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_classify_alarm_by_heuristic():
    with (
        patch(
            "app.harness.routing.router.is_alarm_message",
            return_value=True,
        ),
        patch(
            "app.harness.routing.router.classify_intent",
            new=AsyncMock(),
        ) as intent_mock,
    ):
        decision = await classify("告警原文…")

    assert decision.agent_id == "alarm"
    assert decision.reason == "is_alarm_message"
    assert decision.confidence == 1.0
    intent_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_classify_uses_intent_for_knowledge():
    with (
        patch(
            "app.harness.routing.router.is_alarm_message",
            return_value=False,
        ),
        patch(
            "app.harness.routing.router.classify_intent",
            new=AsyncMock(return_value=IntentEnum.KNOWLEDGE),
        ) as intent_mock,
    ):
        decision = await classify("如何配置监控？", history=[])

    assert decision.agent_id == "knowledge"
    assert decision.reason == "classify_intent"
    intent_mock.assert_awaited_once_with("如何配置监控？", [])


@pytest.mark.asyncio
async def test_classify_maps_order_to_chat():
    with (
        patch(
            "app.harness.routing.router.is_alarm_message",
            return_value=False,
        ),
        patch(
            "app.harness.routing.router.classify_intent",
            new=AsyncMock(return_value=IntentEnum.ORDER),
        ),
    ):
        decision = await classify("查一下订单")

    assert decision.agent_id == "chat"
