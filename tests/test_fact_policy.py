"""Memory-M4-1：可记忆 / 不可记忆分类规则。"""
from __future__ import annotations

from app.services.memory.fact_policy import (
    classify_fact_payload,
    decide_initial_status,
    should_persist_fact,
)


def test_reject_weather():
    ok, decision, reason = should_persist_fact(
        kind="business_fact",
        normalized_key="today_weather",
        content="今天北京下雨",
        source_type="explicit",
        confidence=0.99,
    )
    assert ok is False
    assert decision == "reject"
    assert "forbidden" in reason


def test_reject_order_status_key():
    ok, decision, _ = should_persist_fact(
        kind="business_fact",
        normalized_key="order_status_O1001",
        content="订单已发货",
        source_type="explicit",
        confidence=1.0,
    )
    assert ok is False
    assert decision == "reject"


def test_inferred_preference_is_candidate_only():
    ok, decision, _ = should_persist_fact(
        kind="preference",
        normalized_key="response_style",
        content="用户似乎喜欢简洁回复",
        source_type="inferred",
        confidence=0.9,
    )
    assert ok is True
    assert decision == "candidate"
    assert decide_initial_status(decision) == "candidate"


def test_explicit_high_confidence_active():
    ok, decision, _ = should_persist_fact(
        kind="profile",
        normalized_key="display_name",
        content="用户叫小明",
        source_type="explicit",
        confidence=0.95,
    )
    assert ok is True
    assert decision == "active"


def test_explicit_low_confidence_candidate():
    ok, decision, _ = should_persist_fact(
        kind="preference",
        normalized_key="response_style",
        content="请简洁回复",
        source_type="explicit",
        confidence=0.4,
    )
    assert ok is True
    assert decision == "candidate"


def test_sensitive_inferred_rejected():
    ok, decision, _ = should_persist_fact(
        kind="profile",
        normalized_key="phone_hint",
        content="可能是手机号相关偏好",
        source_type="inferred",
        confidence=0.9,
        sensitive=True,
    )
    assert ok is False
    assert decision == "reject"


def test_classify_fact_payload():
    ok, decision, _ = classify_fact_payload(
        {
            "kind": "constraint",
            "normalized_key": "no_phone_contact",
            "content": "不要打电话联系我",
            "source_type": "explicit",
            "confidence": 0.9,
        }
    )
    assert ok and decision == "active"
