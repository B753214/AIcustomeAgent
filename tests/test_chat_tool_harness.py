"""chat_graph 在 Harness ToolRunBinding 下走 ToolRunner / 白名单。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from app.agents.chat_graph import call_tools
from app.harness.contracts import RunContext, RunRequest
from app.harness.policies import ToolPolicy
from app.harness.registry import get_builtin_tool_registry
from app.harness.runtime.cancellation import CancellationToken
from app.harness.tools import ToolRunner, tool_run_scope


def _ctx() -> RunContext:
    return RunContext(
        run_id="run-tools",
        request=RunRequest(input="查订单", agent_id="chat", caller="api"),
        cancellation_token=CancellationToken(),
    )


@pytest.mark.asyncio
async def test_call_tools_uses_tool_runner_when_bound():
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_order",
                        "args": {"message": "订单 888888"},
                        "id": "tc1",
                        "type": "tool_call",
                    }
                ],
            )
        ],
        "tool_fail_counts": {},
    }
    with tool_run_scope(
        _ctx(),
        ToolRunner(get_builtin_tool_registry()),
        policy=ToolPolicy(allowlist=["query_order", "query_weather"]),
        allowlist=["query_order", "query_weather"],
    ):
        out = await call_tools(state)

    msg = out["messages"][0]
    assert msg.name == "query_order"
    assert "888888" in msg.content
    assert not str(msg.content).startswith("[TOOL_ERROR]")


@pytest.mark.asyncio
async def test_call_tools_blocks_tool_outside_allowlist():
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_order",
                        "args": {"message": "订单 888888"},
                        "id": "tc1",
                        "type": "tool_call",
                    }
                ],
            )
        ],
        "tool_fail_counts": {},
    }
    with tool_run_scope(
        _ctx(),
        ToolRunner(get_builtin_tool_registry()),
        policy=ToolPolicy(allowlist=["query_weather"]),
        allowlist=["query_weather"],
    ):
        out = await call_tools(state)

    msg = out["messages"][0]
    assert str(msg.content).startswith("[TOOL_ERROR]")
    assert "不在允许列表" in msg.content or "允许" in msg.content


@pytest.mark.asyncio
async def test_call_tools_allows_mcp_via_prefix():
    """MCP 须写进白名单（可用 maps_*）；未写前缀则拦截。"""
    from unittest.mock import AsyncMock, patch
    from langchain_core.tools import StructuredTool
    from app.harness.registry.tool_registry import ToolRegistry

    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "maps_text_search",
                        "args": {"keywords": "景点"},
                        "id": "tc1",
                        "type": "tool_call",
                    }
                ],
            )
        ],
        "tool_fail_counts": {},
    }
    async def search(keywords: str) -> str:
        return "ok"

    mock_tool = StructuredTool.from_function(
        coroutine=search, name="maps_text_search", description="Search places",
    )
    registry = ToolRegistry()
    registry.register_model_tool(mock_tool)
    runner = ToolRunner(registry)

    with tool_run_scope(
        _ctx(),
        runner,
        allowlist=["query_order", "maps_*"],
    ), patch(
        "app.agents.chat_graph._ainvoke_tool_with_timeout",
        new=AsyncMock(side_effect=AssertionError("MCP must use ToolRunner")),
    ):
        out = await call_tools(state)

    msg = out["messages"][0]
    assert msg.name == "maps_text_search"
    assert msg.content == "ok"
    assert not str(msg.content).startswith("[TOOL_ERROR]")
