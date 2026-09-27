"""Memory-M3-1：Token 估算器。"""
from __future__ import annotations

from app.services.memory.token_estimate import (
    _fallback_estimate,
    estimate_messages,
    estimate_text,
)


def test_estimate_text_empty():
    assert estimate_text("") == 0
    assert estimate_text(None) == 0  # type: ignore[arg-type]


def test_estimate_text_non_decreasing():
    a = estimate_text("你好")
    b = estimate_text("你好世界，这是一段更长的文本。")
    assert a >= 1
    assert b >= a


def test_estimate_text_english():
    n = estimate_text("hello world")
    assert n >= 1


def test_fallback_positive():
    assert _fallback_estimate("") == 0
    assert _fallback_estimate("ab") >= 1


def test_estimate_messages_sums():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello there"},
    ]
    one = estimate_text("user: hi") + 4
    total = estimate_messages(msgs)
    assert total >= one
    assert total > estimate_text("hi")
    assert estimate_messages([]) == 0
    assert estimate_messages(None) == 0  # type: ignore[arg-type]
