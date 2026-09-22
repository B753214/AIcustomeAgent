"""工具参数校验单测。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from app.agents.chat_graph import TOOL_ERROR_PREFIX, call_tools
from app.agents.tool_validation import (
    QueryOrderArgs,
    QueryWeatherArgs,
    validate_tool_args,
)


def test_query_order_args_ok():
    m = QueryOrderArgs.model_validate({"message": " 查订单 888888 "})
    assert m.message == "查订单 888888"


def test_query_order_args_empty():
    with pytest.raises(Exception):
        QueryOrderArgs.model_validate({"message": "   "})


def test_query_weather_args_rejects_bad_chars():
    with pytest.raises(Exception):
        QueryWeatherArgs.model_validate({"location": "<script>alert(1)</script>"})


def test_query_weather_args_ok_chinese():
    m = QueryWeatherArgs.model_validate({"location": " 杭州 "})
    assert m.location == "杭州"


def test_validate_tool_args_local_weather():
    class Dummy:
        args_schema = QueryWeatherArgs

    cleaned, err = validate_tool_args(Dummy(), "query_weather", {"location": "beijing"})
    assert err is None
    assert cleaned == {"location": "beijing"}


def test_validate_tool_args_invalid_weather():
    class Dummy:
        args_schema = QueryWeatherArgs

    cleaned, err = validate_tool_args(Dummy(), "query_weather", {"location": ""})
    assert cleaned is None
    assert err is not None
    assert err.startswith(TOOL_ERROR_PREFIX)
    assert "参数无效" in err


def test_validate_mcp_schema():
    class MapsArgs(BaseModel):
        keywords: str = Field(..., min_length=1, max_length=50)

    class Dummy:
        args_schema = MapsArgs

    cleaned, err = validate_tool_args(Dummy(), "maps_text_search", {"keywords": "景点"})
    assert err is None
    assert cleaned == {"keywords": "景点"}

    cleaned, err = validate_tool_args(Dummy(), "maps_text_search", {})
    assert cleaned is None
    assert "参数无效" in (err or "")


@pytest.mark.asyncio
async def test_call_tools_rejects_invalid_args(monkeypatch):
    async def _fake_timeout(tool, args, name):
        return "should-not-run"

    monkeypatch.setattr(
        "app.agents.chat_graph._ainvoke_tool_with_timeout",
        _fake_timeout,
    )
    # 避免拉高德
    monkeypatch.setattr("app.agents.chat_graph._extra_tools", [])
    monkeypatch.setattr("app.agents.chat_graph._extra_tools_loaded", True)

    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_weather",
                        "args": {"location": ""},
                        "id": "t1",
                    }
                ],
            )
        ],
        "tool_fail_counts": {},
    }
    out = await call_tools(state)
    msg = out["messages"][0]
    assert msg.content.startswith(TOOL_ERROR_PREFIX)
    assert "参数无效" in msg.content
    assert out["tool_fail_counts"].get("query_weather", 0) >= 1
