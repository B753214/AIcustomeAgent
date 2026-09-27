"""Memory-M3-4：滚动摘要切分与文本化。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.schema.memory_summary import SessionSummaryPayload
from app.services.memory.summary_service import (
    format_summary,
    maybe_summarize,
    split_for_summary,
)


def _msg(i: int, content: str = "x") -> dict:
    role = "user" if i % 2 == 0 else "assistant"
    return {"role": role, "content": f"{i}:{content}"}


def test_split_below_threshold_keeps_all():
    # keep=3 → 6 条；old 只有 2 轮 < min_turns=6 → 不切
    history = [_msg(i) for i in range(10)]  # 5 轮
    old, recent = split_for_summary(history, min_turns=6, keep_turns=3)
    assert old == []
    assert recent == history


def test_split_summarizes_old_keeps_recent():
    # 10 轮 = 20 条；keep=3 → recent 6 条；old 7 轮 >= 6
    history = [_msg(i) for i in range(20)]
    old, recent = split_for_summary(history, min_turns=6, keep_turns=3)
    assert len(old) == 14
    assert len(recent) == 6
    assert old[-1]["content"].startswith("13:")
    assert recent[0]["content"].startswith("14:")


def test_format_summary_text():
    payload = SessionSummaryPayload(
        topic="订单延迟",
        known_facts=["用户叫小明"],
        decisions=["先等物流"],
        unresolved=["是否改址"],
    )
    text = format_summary(payload)
    assert text.startswith("【会话摘要】")
    assert "小明" in text
    assert "先等物流" in text


@pytest.mark.asyncio
async def test_maybe_summarize_calls_llm_on_old_only():
    history = [_msg(i) for i in range(20)]
    fake = SessionSummaryPayload(topic="t", known_facts=["小明"])

    with patch(
        "app.services.memory.summary_service.summarize_messages",
        new_callable=AsyncMock,
        return_value=fake,
    ) as mocked:
        summary, recent = await maybe_summarize(history)

    assert summary is fake
    assert len(recent) == 6
    mocked.assert_awaited_once()
    old_arg = mocked.await_args.args[0]
    assert len(old_arg) == 14
    assert old_arg[0]["content"].startswith("0:")


@pytest.mark.asyncio
async def test_maybe_summarize_failure_returns_full_history(caplog):
    history = [_msg(i) for i in range(20)]

    with (
        patch(
            "app.services.memory.summary_service.summarize_messages",
            new_callable=AsyncMock,
            side_effect=RuntimeError("llm down"),
        ),
        caplog.at_level("WARNING", logger="airobot.memory"),
    ):
        summary, recent = await maybe_summarize(history)

    assert summary is None
    assert recent == history
    assert any("session summary failed" in r.message for r in caplog.records)
