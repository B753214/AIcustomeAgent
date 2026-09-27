"""Memory-M2-5：历史简略/详细模式。"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.sessions import ChatMessage
from app.services.session_service import load_session_history


def _msg(**kwargs) -> ChatMessage:
    defaults = dict(
        session_id="s1",
        role="assistant",
        content="hello",
        intent="knowledge",
        engine="harness",
        run_id="r1",
        message_metadata={"sources": ["a#1"]},
        created_at=datetime(2026, 1, 1, 12, 0, 0),
    )
    defaults.update(kwargs)
    return ChatMessage(**defaults)


@pytest.mark.asyncio
async def test_load_history_brief_omits_trace_fields():
    db = AsyncMock()
    sess = MagicMock()
    sess.session_id = "s1"
    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = sess
    msg_result = MagicMock()
    msg_result.scalars.return_value.all.return_value = [_msg()]
    db.execute = AsyncMock(side_effect=[get_result, msg_result])

    out = await load_session_history(
        "s1", "u1", db, create_if_missing=False, detail=False
    )
    assert out == [{"role": "assistant", "content": "hello"}]


@pytest.mark.asyncio
async def test_load_history_detail_includes_trace_fields():
    db = AsyncMock()
    sess = MagicMock()
    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = sess
    msg_result = MagicMock()
    msg_result.scalars.return_value.all.return_value = [_msg()]
    db.execute = AsyncMock(side_effect=[get_result, msg_result])

    out = await load_session_history(
        "s1", "u1", db, create_if_missing=False, detail=True
    )
    assert len(out) == 1
    assert out[0]["role"] == "assistant"
    assert out[0]["content"] == "hello"
    assert out[0]["intent"] == "knowledge"
    assert out[0]["engine"] == "harness"
    assert out[0]["run_id"] == "r1"
    assert out[0]["metadata"] == {"sources": ["a#1"]}
    assert out[0]["created_at"] == "2026-01-01T12:00:00"
