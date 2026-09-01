"""高德 MCP：供 LangGraph（LC StructuredTool）与 Crew（Crew Tool）共用。"""
from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.config import settings

_amap_tools: list | None = None
_amap_crew_tools: list | None = None


async def get_amap_tools() -> list:
    """LangChain StructuredTool 列表（chat_graph 用 ainvoke）。"""
    global _amap_tools
    if _amap_tools is not None:
        return _amap_tools
    if not settings.amap_mcp_enabled or not settings.amap_maps_api_key:
        _amap_tools = []
        return _amap_tools
    try:
        url = f"{settings.amap_mcp_url}?key={settings.amap_maps_api_key}"
        client = MultiServerMCPClient(
            {
                "amap": {
                    "url": url,
                    "transport": "streamable_http",
                }
            }
        )
        _amap_tools = await client.get_tools()
    except Exception as e:
        print(f"[amap_mcp] 拉取工具失败: {e}")
        _amap_tools = []
    return _amap_tools


def _run_async(coro):
    """在同步上下文执行协程。

    已有 running loop 时不能 asyncio.run（会嵌套），改到独立线程里跑新 loop，
    避免和 FastAPI/kickoff_async 的主 loop、以及 asyncpg 连接绑死在同一线程上冲突。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    def _in_thread():
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_in_thread).result()


def _lc_tool_to_crew(lc_tool: Any):
    """LangChain StructuredTool → CrewAI Tool（同步壳调 ainvoke）。"""
    from crewai.tools import tool

    name = getattr(lc_tool, "name", None) or "amap_tool"
    desc = getattr(lc_tool, "description", None) or name

    def _run(**kwargs) -> str:
        try:
            out = _run_async(lc_tool.ainvoke(kwargs))
            return str(out)
        except Exception as e:
            return f"[TOOL_ERROR] 工具 {name} 异常: {e}"

    _run.__name__ = str(name).replace("-", "_")
    _run.__doc__ = desc
    return tool(name)(_run)


async def get_amap_crew_tools() -> list:
    """Crew 可直接挂载的工具列表；关开关或未装 crewai 时为 []。"""
    global _amap_crew_tools
    if _amap_crew_tools is not None:
        return _amap_crew_tools

    lc_tools = await get_amap_tools()
    if not lc_tools:
        _amap_crew_tools = []
        return _amap_crew_tools
    try:
        _amap_crew_tools = [_lc_tool_to_crew(t) for t in lc_tools]
    except ImportError:
        print("[amap_mcp] crewai 未安装，跳过高德 Crew 工具")
        _amap_crew_tools = []
    except Exception as e:
        print(f"[amap_mcp] 转换 Crew 工具失败: {e}")
        _amap_crew_tools = []
    return _amap_crew_tools


async def main():
    tools = await get_amap_tools()
    print("lc:", len(tools), [t.name for t in tools])
    crew_tools = await get_amap_crew_tools()
    print("crew:", len(crew_tools), [getattr(t, "name", t) for t in crew_tools])


if __name__ == "__main__":
    asyncio.run(main())
