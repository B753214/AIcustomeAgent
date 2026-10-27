"""Harness 高德 MCP 发现与注册；业务 Agent 不管理远端连接。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import settings
from app.harness.registry.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)
_tools: list[Any] | None = None
_load_lock = asyncio.Lock()


async def get_amap_tools() -> list[Any]:
    global _tools
    if _tools is not None:
        return _tools
    async with _load_lock:
        if _tools is not None:
            return _tools
        if not settings.amap_mcp_enabled or not settings.amap_maps_api_key:
            _tools = []
            return _tools
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient({"amap": {
            "url": f"{settings.amap_mcp_url}?key={settings.amap_maps_api_key}",
            "transport": "streamable_http",
        }})
        try:
            _tools = await client.get_tools()
        except Exception as exc:
            # 不输出 URL/异常正文，避免包含连接凭据；失败允许下次加载重试。
            logger.warning("高德 MCP 工具发现失败 (%s)", type(exc).__name__)
            return []
        return _tools


async def ensure_mcp_tools(registry: ToolRegistry) -> list[Any]:
    """加载成功后同步注册；重复准备不覆盖既有工具或放宽 Agent 权限。"""
    tools = await get_amap_tools()
    names = set(registry.list_names())
    timeout = float(settings.tool_timeout_sec or 30.0)
    for tool in tools:
        if tool.name in names:
            if registry.has_model_tool(tool):
                continue
            raise ValueError(f"MCP tool {tool.name!r} conflicts with registered tool")
        registry.register_model_tool(tool, timeout_sec=timeout)
        names.add(tool.name)
    return tools
