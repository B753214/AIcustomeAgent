"""Day10：chat_intent 抽链解析 + resolve mock（不调真实 LLM）。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.alarm.chat_intent import (
    extract_analyze_url_from_reply,
    resolve_analyze_url,
    strip_think,
)


def test_strip_think():
    raw = "<think>secret</think>\n你好"
    assert strip_think(raw) == "你好"


def test_extract_analyze_url_from_reply():
    url = (
        "https://info-plate.fc.alibaba-inc.com/monitor/searchall"
        "?bizType=30&marketConfigId=11664&startTime=1&endTime=2"
    )
    text = f'{{"action":"analyze","url":"{url}"}}'
    assert extract_analyze_url_from_reply(text) == url


def test_extract_analyze_url_with_spaces_and_think():
    url = (
        "https://info-plate.fc.alibaba-inc.com/monitor/searchall"
        "?bizType=30&marketConfigId=11664&startTime=100&endTime=200"
    )
    text = f'<think>x</think>\n{{"action" : "analyze" , "url" : "{url}"}}'
    assert extract_analyze_url_from_reply(text) == url


def test_extract_analyze_url_none_for_chat():
    assert extract_analyze_url_from_reply("你好，我是监控助手") is None
    assert extract_analyze_url_from_reply("") is None


@pytest.mark.asyncio
async def test_resolve_analyze_url_returns_url():
    url = (
        "https://info-plate.fc.alibaba-inc.com/monitor/searchall"
        "?bizType=30&marketConfigId=11664&startTime=1&endTime=2"
    )
    reply = f'{{"action":"analyze","url":"{url}"}}'
    with (
        patch("app.agents.alarm.chat_intent._build_llm", return_value=MagicMock()),
        patch(
            "app.agents.alarm.chat_intent.ainvoke_with_retry",
            new=AsyncMock(return_value=SimpleNamespace(content=reply)),
        ),
    ):
        got_url, chat = await resolve_analyze_url("configId=11664 最近1小时")
    assert got_url == url
    assert chat is None


@pytest.mark.asyncio
async def test_resolve_analyze_url_chat_only():
    with (
        patch("app.agents.alarm.chat_intent._build_llm", return_value=MagicMock()),
        patch(
            "app.agents.alarm.chat_intent.ainvoke_with_retry",
            new=AsyncMock(return_value=SimpleNamespace(content="你好，有什么可以帮你")),
        ),
    ):
        got_url, chat = await resolve_analyze_url("今天天气怎么样")
    assert got_url is None
    assert "帮你" in chat


@pytest.mark.asyncio
async def test_resolve_analyze_url_llm_failure_fallback():
    with patch(
        "app.agents.alarm.chat_intent._build_llm",
        side_effect=RuntimeError("boom"),
    ):
        got_url, chat = await resolve_analyze_url("随便")
    assert got_url is None
    assert "info-plate" in chat
