"""Memory-M3-3：SessionSummaryPayload 结构化摘要 Schema。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schema.memory_summary import SessionSummaryPayload


def test_valid_full_payload():
    payload = SessionSummaryPayload.model_validate(
        {
            "topic": "排查订单延迟",
            "known_facts": ["用户订单号 O-1001", "已查物流在途"],
            "decisions": ["先等物流更新再催"],
            "unresolved": ["是否需要改址"],
        }
    )
    assert payload.topic == "排查订单延迟"
    assert len(payload.known_facts) == 2
    assert payload.decisions == ["先等物流更新再催"]
    assert payload.unresolved == ["是否需要改址"]


def test_lists_default_empty():
    payload = SessionSummaryPayload.model_validate({"topic": "闲聊天气"})
    assert payload.known_facts == []
    assert payload.decisions == []
    assert payload.unresolved == []


def test_none_lists_become_empty():
    payload = SessionSummaryPayload.model_validate(
        {
            "topic": "告警跟进",
            "known_facts": None,
            "decisions": None,
            "unresolved": None,
        }
    )
    assert payload.known_facts == []
    assert payload.decisions == []
    assert payload.unresolved == []


def test_topic_stripped_and_required():
    payload = SessionSummaryPayload.model_validate({"topic": "  主题  "})
    assert payload.topic == "主题"

    with pytest.raises(ValidationError):
        SessionSummaryPayload.model_validate({"topic": "   "})

    with pytest.raises(ValidationError):
        SessionSummaryPayload.model_validate({})


def test_rejects_extra_fields():
    with pytest.raises(ValidationError):
        SessionSummaryPayload.model_validate(
            {
                "topic": "x",
                "known_facts": [],
                "decisions": [],
                "unresolved": [],
                "extra_key": 1,
            }
        )


def test_rejects_wrong_list_item_type():
    with pytest.raises(ValidationError):
        SessionSummaryPayload.model_validate(
            {"topic": "x", "known_facts": [1, 2]}
        )
