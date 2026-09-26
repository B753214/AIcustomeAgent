"""Memory-M1-6：ChatRequest / user_id 入参校验（不连真库）。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import settings
from app.schemas import ChatRequest


def test_message_ok():
    req = ChatRequest(message="你好")
    assert req.message == "你好"
    assert req.session_id is None


def test_message_strips_and_rejects_blank():
    req = ChatRequest(message="  hi  ")
    assert req.message == "hi"
    with pytest.raises(ValidationError):
        ChatRequest(message="   ")


def test_message_too_long():
    with pytest.raises(ValidationError):
        ChatRequest(message="x" * (settings.chat_message_max_chars + 1))


def test_session_id_rejects_default():
    with pytest.raises(ValidationError) as ei:
        ChatRequest(message="hi", session_id="default")
    assert "default" in str(ei.value).lower()

    with pytest.raises(ValidationError):
        ChatRequest(message="hi", session_id="DEFAULT")


def test_session_id_empty_becomes_none():
    req = ChatRequest(message="hi", session_id="  ")
    assert req.session_id is None


def test_session_id_too_long():
    with pytest.raises(ValidationError):
        ChatRequest(
            message="hi",
            session_id="a" * (settings.max_session_id_length + 1),
        )


@pytest.mark.asyncio
async def test_user_id_too_long():
    from app.services.auth import get_user_id

    with pytest.raises(Exception) as ei:
        await get_user_id(x_user_id="u" * (settings.max_user_id_length + 1))
    assert getattr(ei.value, "status_code", None) == 400
