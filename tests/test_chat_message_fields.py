"""Memory-M2-1：chat_messages 扩展字段（不连真库）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.sessions import ChatMessage
from app.services.session_service import save_message


def test_chat_message_metadata_column_mapping():
    assert "metadata" in ChatMessage.__table__.c
    assert ChatMessage.message_metadata.property.columns[0].name == "metadata"


@pytest.mark.asyncio
async def test_save_message_accepts_optional_fields():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    msg = await save_message(
        "s1",
        "assistant",
        "hello",
        db,
        intent="chat",
        engine="harness",
        run_id="r1",
        metadata={"sources": ["a"]},
    )
    assert msg.intent == "chat"
    assert msg.engine == "harness"
    assert msg.run_id == "r1"
    assert msg.message_metadata == {"sources": ["a"]}
    db.add.assert_called_once_with(msg)
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_save_message_legacy_call_ok():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    msg = await save_message("s1", "user", "hi", db)
    assert msg.intent is None
    assert msg.run_id is None
