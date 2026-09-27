"""Memory-M3-2/M3-4：Token Budget 裁剪与摘要前置。"""
from __future__ import annotations

from unittest.mock import patch

from app.schema.memory_summary import SessionSummaryPayload
from app.services.memory.context_builder import build_recent_context


def _msg(i: int, content: str = "x" * 20) -> dict:
    role = "user" if i % 2 == 0 else "assistant"
    return {"role": role, "content": f"{i}:{content}"}


def test_short_history_unchanged():
    history = [_msg(0, "hi"), _msg(1, "hello")]
    out = build_recent_context(
        history,
        current_message="q",
        budget=3000,
        max_turns=5,
        system_reserve=0,
    )
    assert out == history
    assert len(history) == 2


def test_trims_by_token_budget():
    history = [_msg(i, "字" * 50) for i in range(20)]

    def fake_estimate_messages(msgs):
        return len(msgs) * 100

    def fake_estimate_text(text):
        return 10

    with (
        patch(
            "app.services.memory.context_builder.estimate_messages",
            side_effect=fake_estimate_messages,
        ),
        patch(
            "app.services.memory.context_builder.estimate_text",
            side_effect=fake_estimate_text,
        ),
    ):
        out = build_recent_context(
            history,
            current_message="q",
            budget=350,
            max_turns=50,
            system_reserve=0,
        )
    assert len(out) == 3
    assert out[0]["content"].startswith("17:")
    assert out[-1]["content"].startswith("19:")


def test_max_turns_secondary_cap():
    history = [_msg(i) for i in range(20)]
    out = build_recent_context(
        history,
        current_message="",
        budget=100_000,
        max_turns=2,
        system_reserve=0,
    )
    assert len(out) == 4


def test_empty_history():
    assert build_recent_context([], current_message="hi", budget=100) == []
    assert build_recent_context(None, current_message="hi", budget=100) == []


def test_summary_prepended_as_system_text():
    history = [_msg(0), _msg(1)]
    summary = SessionSummaryPayload(
        topic="主题A",
        known_facts=["用户叫小明"],
        decisions=[],
        unresolved=[],
    )
    out = build_recent_context(
        history,
        current_message="q",
        budget=100_000,
        max_turns=5,
        system_reserve=0,
        summary=summary,
    )
    assert out[0]["role"] == "system"
    assert isinstance(out[0]["content"], str)
    assert "小明" in out[0]["content"]
    assert out[1:] == history


def test_summary_skips_max_turns_cap():
    history = [_msg(i) for i in range(10)]
    summary = SessionSummaryPayload(topic="t")
    out = build_recent_context(
        history,
        current_message="",
        budget=100_000,
        max_turns=1,
        system_reserve=0,
        summary=summary,
    )
    assert len(out) == 11
    assert out[0]["role"] == "system"


def test_trim_drops_raw_keeps_summary_first():
    history = [_msg(i, "字" * 40) for i in range(10)]
    summary = SessionSummaryPayload(topic="保留摘要")

    def fake_estimate_messages(msgs):
        return len(msgs) * 100

    with (
        patch(
            "app.services.memory.context_builder.estimate_messages",
            side_effect=fake_estimate_messages,
        ),
        patch(
            "app.services.memory.context_builder.estimate_text",
            return_value=0,
        ),
    ):
        out = build_recent_context(
            history,
            current_message="",
            budget=250,
            max_turns=50,
            system_reserve=0,
            summary=summary,
        )
    assert out[0]["role"] == "system"
    assert "保留摘要" in out[0]["content"]
    assert len(out) == 2
