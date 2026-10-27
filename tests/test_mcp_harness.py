"""离线验证 MCP 发现、注册、模型可见性和统一执行路径。"""
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import StructuredTool

from app.agents.chat_graph import _tools_for_binding, ensure_chat_tools
from app.harness.contracts import HarnessError, RunContext, RunRequest
from app.harness.registry.tool_registry import ToolRegistry, register_builtin_tools
from app.harness.tools import ToolRunner, tool_run_scope
from app.harness.tools import mcp
from app.harness.policies import ToolPolicy


def make_tool():
    async def search(keywords: str) -> str:
        return f"result:{keywords}"
    return StructuredTool.from_function(
        coroutine=search, name="maps_text_search", description="Search places",
    )


def context():
    return RunContext(run_id="mcp-test", request=RunRequest(input="search", agent_id="chat"))


@pytest.mark.asyncio
async def test_mcp_prepared_and_bound_like_local_tools(monkeypatch):
    tool = make_tool()
    monkeypatch.setattr(mcp, "get_amap_tools", AsyncMock(return_value=[tool]))
    registry = register_builtin_tools(ToolRegistry())
    runner = ToolRunner(registry)
    with tool_run_scope(context(), runner, allowlist=["query_order", "maps_*"]):
        await ensure_chat_tools()
        await ensure_chat_tools()
        assert [t.name for t in _tools_for_binding()] == ["query_order", "maps_text_search"]
        assert await runner.arun("maps_text_search", {"keywords": "杭州"}, context()) == "result:杭州"
    assert registry.get_spec(tool.name).input_schema["required"] == ["keywords"]


@pytest.mark.asyncio
async def test_mcp_not_visible_or_executable_without_permission(monkeypatch):
    tool = make_tool()
    monkeypatch.setattr(mcp, "get_amap_tools", AsyncMock(return_value=[tool]))
    registry = register_builtin_tools(ToolRegistry())
    await mcp.ensure_mcp_tools(registry)
    with tool_run_scope(context(), ToolRunner(registry), allowlist=["query_order"]):
        assert [t.name for t in _tools_for_binding()] == ["query_order"]
    with pytest.raises(HarnessError):
        await ToolRunner(registry).arun(tool.name, {"keywords": "杭州"}, context(),
                                       tool_policy=ToolPolicy(["query_order"]))


@pytest.mark.asyncio
async def test_mcp_timeout_uses_runner():
    import asyncio
    async def slow(keywords: str) -> str:
        await asyncio.sleep(1)
        return "unexpected"
    tool = StructuredTool.from_function(coroutine=slow, name="maps_slow", description="Slow")
    registry = ToolRegistry()
    registry.register_model_tool(tool, timeout_sec=0.01)
    with pytest.raises(HarnessError) as exc:
        await ToolRunner(registry).arun(tool.name, {"keywords": "x"}, context())
    assert exc.value.category.value == "timeout"


@pytest.mark.asyncio
async def test_mcp_cannot_replace_existing_tool(monkeypatch):
    first, second = make_tool(), make_tool()
    registry = ToolRegistry()
    registry.register_model_tool(first)
    monkeypatch.setattr(mcp, "get_amap_tools", AsyncMock(return_value=[second]))
    with pytest.raises(ValueError, match="conflicts"):
        await mcp.ensure_mcp_tools(registry)
    assert registry.has_model_tool(first)


@pytest.mark.asyncio
async def test_discovery_cached_across_concurrent_calls(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock
    tool = make_tool()
    client = MagicMock()
    client.get_tools = AsyncMock(return_value=[tool])
    factory = MagicMock(return_value=client)
    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", factory)
    monkeypatch.setattr(mcp, "_tools", None)
    monkeypatch.setattr(mcp, "_load_lock", asyncio.Lock())
    monkeypatch.setattr(mcp.settings, "amap_mcp_enabled", True)
    monkeypatch.setattr(mcp.settings, "amap_maps_api_key", "test-only")
    results = await asyncio.gather(mcp.get_amap_tools(), mcp.get_amap_tools())
    assert results == [[tool], [tool]]
    client.get_tools.assert_awaited_once()
    factory.assert_called_once()


@pytest.mark.asyncio
async def test_failed_discovery_can_retry_without_logging_key(monkeypatch, caplog):
    import asyncio
    from unittest.mock import MagicMock
    tool = make_tool()
    client = MagicMock()
    client.get_tools = AsyncMock(side_effect=[RuntimeError("secret-key"), [tool]])
    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient",
                        MagicMock(return_value=client))
    monkeypatch.setattr(mcp, "_tools", None)
    monkeypatch.setattr(mcp, "_load_lock", asyncio.Lock())
    monkeypatch.setattr(mcp.settings, "amap_mcp_enabled", True)
    monkeypatch.setattr(mcp.settings, "amap_maps_api_key", "secret-key")
    assert await mcp.get_amap_tools() == []
    assert await mcp.get_amap_tools() == [tool]
    assert "secret-key" not in caplog.text
