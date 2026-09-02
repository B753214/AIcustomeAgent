"""Chat Agent：mock chat_graph.ainvoke（不调真实 LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.chat_graph import TOOL_ERROR_PREFIX, _wrap_tool
from app.agents.chat_react import (
    _collect_tool_errors,
    _collect_tool_names,
    _finalize_reply,
    _last_ai_text,
    iter_chat_react,
    run_chat_react,
)
from app.agents.tools import query_order
from app.agents.weather import query_weather


def test_query_order_is_tool_not_agent():
    text = query_order("查一下订单 888888")
    assert "888888" in text
    assert "已发货" in text


def test_wrap_tool_preserves_tool_error_prefix():
    def fail_weather(location: str) -> str:
        return f"{TOOL_ERROR_PREFIX} 未配置天气 Key，暂时查不了「{location}」的天气。"

    wrapped = _wrap_tool(fail_weather, "query_weather")
    text = wrapped(location="杭州")
    assert text.startswith(TOOL_ERROR_PREFIX)
    assert "未配置" in text


def test_query_weather_empty_key_errors():
    text = query_weather("杭州")
    assert text.startswith(TOOL_ERROR_PREFIX)


def test_wrap_tool_exception_becomes_tool_error():
    def boom(**kwargs):
        raise RuntimeError("network down")

    wrapped = _wrap_tool(boom, "query_weather")
    text = wrapped(location="杭州")
    assert text.startswith(TOOL_ERROR_PREFIX)
    assert "network down" in text


def test_collect_tool_errors():
    msgs = [
        ToolMessage(
            content=f"{TOOL_ERROR_PREFIX} 天气查询失败",
            tool_call_id="1",
            name="query_weather",
        ),
        ToolMessage(content="晴 26℃", tool_call_id="2", name="query_weather"),
    ]
    errs = _collect_tool_errors(msgs)
    assert len(errs) == 1
    assert errs[0].startswith(TOOL_ERROR_PREFIX)


def test_finalize_reply_uses_tool_error_when_empty():
    out = _finalize_reply("", [f"{TOOL_ERROR_PREFIX} 未配置 Key"])
    assert "未配置 Key" in out
    assert TOOL_ERROR_PREFIX not in out


def test_collect_tool_names_from_ai_tool_calls():
    msgs = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "query_order", "args": {"message": "1"}, "id": "c1"},
            ],
        ),
        AIMessage(content="已发货"),
    ]
    assert _collect_tool_names(msgs) == ["query_order"]


def test_last_ai_text():
    msgs = [
        HumanMessage(content="hi"),
        AIMessage(content="你好"),
    ]
    assert _last_ai_text(msgs) == "你好"


@pytest.mark.asyncio
async def test_run_chat_react_calls_query_order():
    fake_result = {
        "messages": [
            HumanMessage(content="查订单 202608090001"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_order",
                        "args": {"message": "订单 202608090001"},
                        "id": "c1",
                    }
                ],
            ),
            AIMessage(content="订单已发货，顺丰在途。"),
        ],
        "tool_fail_counts": {},
    }
    with patch(
        "app.agents.chat_react.chat_graph.ainvoke",
        new=AsyncMock(return_value=fake_result),
    ):
        res = await run_chat_react("查订单 202608090001")
    assert res["engine"] == "chat_react"
    assert res["intent"] == "order"
    assert "query_order" in res["meta"]["tool_calls"]
    assert "已发货" in res["reply"]


@pytest.mark.asyncio
async def test_run_chat_react_calls_query_weather():
    fake_result = {
        "messages": [
            HumanMessage(content="杭州天气怎么样"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_weather",
                        "args": {"location": "杭州"},
                        "id": "c1",
                    }
                ],
            ),
            AIMessage(content="杭州今天晴，气温 26℃。"),
        ],
        "tool_fail_counts": {},
    }
    with patch(
        "app.agents.chat_react.chat_graph.ainvoke",
        new=AsyncMock(return_value=fake_result),
    ):
        res = await run_chat_react("杭州天气怎么样")
    assert "query_weather" in res["meta"]["tool_calls"]
    assert res["intent"] == "chat"


@pytest.mark.asyncio
async def test_run_chat_react_plain_hi():
    fake_result = {
        "messages": [
            HumanMessage(content="你好"),
            AIMessage(content="你好，有什么可以帮你"),
        ],
        "tool_fail_counts": {},
    }
    with patch(
        "app.agents.chat_react.chat_graph.ainvoke",
        new=AsyncMock(return_value=fake_result),
    ):
        res = await run_chat_react("你好")
    assert res["meta"]["tool_calls"] == []
    assert "帮你" in res["reply"]


async def _fake_astream_events_hi(*args, **kwargs):
    from langchain_core.messages import AIMessageChunk

    yield {
        "event": "on_chat_model_stream",
        "data": {"chunk": AIMessageChunk(content="你好，")},
    }
    yield {
        "event": "on_chat_model_stream",
        "data": {"chunk": AIMessageChunk(content="有什么可以帮你")},
    }
    yield {
        "event": "on_chat_model_end",
        "data": {"output": AIMessage(content="你好，有什么可以帮你")},
    }
    yield {
        "event": "on_chain_end",
        "name": "call_model",
        "data": {
            "output": {
                "messages": [AIMessage(content="你好，有什么可以帮你")],
            }
        },
    }


async def _fake_astream_events_order(*args, **kwargs):
    from langchain_core.messages import AIMessageChunk

    first_ai = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "query_order",
                "args": {"message": "订单 888888"},
                "id": "c1",
            }
        ],
    )
    yield {
        "event": "on_chat_model_end",
        "data": {"output": first_ai},
    }
    yield {
        "event": "on_chain_end",
        "name": "call_model",
        "data": {"output": {"messages": [first_ai]}},
    }
    yield {
        "event": "on_chain_end",
        "name": "call_tools",
        "data": {
            "output": {
                "messages": [
                    ToolMessage(
                        content="订单 888888 已发货。",
                        tool_call_id="c1",
                        name="query_order",
                    )
                ],
                "tool_fail_counts": {},
            }
        },
    }
    yield {
        "event": "on_chat_model_stream",
        "data": {"chunk": AIMessageChunk(content="订单已发货。")},
    }
    yield {
        "event": "on_chat_model_end",
        "data": {"output": AIMessage(content="订单已发货。")},
    }
    yield {
        "event": "on_chain_end",
        "name": "call_model",
        "data": {"output": {"messages": [AIMessage(content="订单已发货。")]}},
    }


@pytest.mark.asyncio
async def test_iter_chat_react_plain_hi():
    with patch(
        "app.agents.chat_react.chat_graph.astream_events",
        side_effect=_fake_astream_events_hi,
    ):
        events = [ev async for ev in iter_chat_react("你好")]
    types = [ev["type"] for ev in events]
    assert types == ["stage", "token", "token", "result"]
    assert events[0]["stage"] == "chat_react"
    assert events[1]["content"] == "你好，"
    assert events[2]["content"] == "有什么可以帮你"
    assert "帮你" in events[-1]["reply"]


@pytest.mark.asyncio
async def test_iter_chat_react_yields_tool_stage():
    with patch(
        "app.agents.chat_react.chat_graph.astream_events",
        side_effect=_fake_astream_events_order,
    ):
        events = [ev async for ev in iter_chat_react("查订单 888888")]
    stages = [ev.get("stage") for ev in events if ev.get("type") == "stage"]
    tokens = [ev.get("content") for ev in events if ev.get("type") == "token"]
    assert stages == ["chat_react", "tool"]
    assert tokens == ["订单已发货。"]
    assert events[-1]["type"] == "result"
    assert "query_order" in events[-1]["meta"]["tool_calls"]
