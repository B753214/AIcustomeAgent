"""Memory-M3-4/M3-5/M3-6：滚动摘要切分、失败降级、缓存命中。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schema.memory_summary import SessionSummaryPayload
from app.services.memory.summary_service import (
    _cache_hit,
    format_summary,
    maybe_summarize,
    split_for_summary,
)


def _msg(i: int, content: str = "x") -> dict:
    role = "user" if i % 2 == 0 else "assistant"
    return {"id": f"m{i}", "role": role, "content": f"{i}:{content}"}


def test_split_below_threshold_keeps_all():
    history = [_msg(i) for i in range(10)]
    old, recent = split_for_summary(history, min_turns=6, keep_turns=3)
    assert old == []
    assert recent == history


def test_split_summarizes_old_keeps_recent():
    history = [_msg(i) for i in range(20)]
    old, recent = split_for_summary(history, min_turns=6, keep_turns=3)
    assert len(old) == 14
    assert len(recent) == 6
    assert old[-1]["id"] == "m13"
    assert recent[0]["id"] == "m14"


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


def test_cache_hit_requires_version_and_through():
    old = [_msg(i) for i in range(14)]
    assert _cache_hit(
        stored_version="v1",
        through_message_id="m13",
        old=old,
        prompt_version="v1",
    )
    assert not _cache_hit(
        stored_version="v1",
        through_message_id="m13",
        old=old,
        prompt_version="v2",
    )
    assert not _cache_hit(
        stored_version="v1",
        through_message_id="m12",
        old=old,
        prompt_version="v1",
    )


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
    assert mocked.await_args.args[0][-1]["id"] == "m13"


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


@pytest.mark.asyncio
async def test_maybe_summarize_cache_hit_skips_llm():
    history = [_msg(i) for i in range(20)]
    payload = {"topic": "缓存主题", "known_facts": ["小明"], "decisions": [], "unresolved": []}
    row = SimpleNamespace(
        summary=payload,
        through_message_id="m13",
        prompt_version="v1",
    )
    db = MagicMock()

    with (
        patch(
            "app.services.memory.summary_service.get_session_summary",
            new_callable=AsyncMock,
            return_value=row,
        ),
        patch(
            "app.services.memory.summary_service.summarize_messages",
            new_callable=AsyncMock,
        ) as mocked_llm,
        patch(
            "app.services.memory.summary_service.settings"
        ) as mock_settings,
    ):
        mock_settings.memory_summary_min_turns = 6
        mock_settings.memory_summary_keep_turns = 3
        mock_settings.memory_summary_prompt_version = "v1"
        summary, recent = await maybe_summarize(
            history, session_id="s1", db=db
        )

    assert summary is not None
    assert summary.topic == "缓存主题"
    assert len(recent) == 6
    mocked_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_summarize_persists_on_miss():
    history = [_msg(i) for i in range(20)]
    fake = SessionSummaryPayload(topic="新摘要")
    db = MagicMock()

    with (
        patch(
            "app.services.memory.summary_service.get_session_summary",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.memory.summary_service.summarize_messages",
            new_callable=AsyncMock,
            return_value=fake,
        ),
        patch(
            "app.services.memory.summary_service.upsert_session_summary",
            new_callable=AsyncMock,
        ) as mocked_upsert,
        patch(
            "app.services.memory.summary_service.settings"
        ) as mock_settings,
    ):
        mock_settings.memory_summary_min_turns = 6
        mock_settings.memory_summary_keep_turns = 3
        mock_settings.memory_summary_prompt_version = "v1"
        summary, _ = await maybe_summarize(history, session_id="s1", db=db)

    assert summary is fake
    mocked_upsert.assert_awaited_once()
    kwargs = mocked_upsert.await_args.kwargs
    assert kwargs["through_message_id"] == "m13"
    assert kwargs["from_message_id"] == "m0"
    assert kwargs["prompt_version"] == "v1"
