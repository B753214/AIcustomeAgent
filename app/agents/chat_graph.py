"""闲聊手写 StateGraph：call_model / call_tools + 失败熔断。"""
from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.agents.tools import query_order
from app.agents.weather import query_weather
from app.config import settings

TOOL_ERROR_PREFIX = "[TOOL_ERROR]"
CHAT_REACT_SYSTEM = f"""你是智能运维 Agent 助手，语气专业、简洁、友好。
你的能力：
1. 闲聊与日常协助（打招呼、问能力等）
2. 需要事实时调用工具；工具返回是唯一事实来源

工具使用：
- 用户查订单号、物流、发货状态 → 先调用 query_order
- 用户问天气、气温、下雨等 → 先调用 query_weather（传入 location，如 beijing）
- 普通打招呼、闲聊、问你是谁/能做什么 → 直接回复，不要调工具
- 前端页面报警、知识库问答不由你处理

工具结果（必须遵守）：
- 每一轮工具返回都会作为观察结果出现在对话中，你必须阅读后再回答
- 若内容以 {TOOL_ERROR_PREFIX} 开头：表示工具调用失败或业务失败；必须把失败原因如实告诉用户，禁止编造订单状态或天气，禁止假装查询成功
- 工具成功时：只依据返回内容总结，不要添加返回里没有的数据
- 不要忽略工具报错去「猜」一个答案
- 若工具返回 [TOOL_ERROR]，可再调用同一工具重试；多次仍失败再向用户说明。
- 若已绑定高德 maps_* 工具：地理/周边/路径/POI 等优先用高德工具；天气仍可用 query_weather，也可按工具描述选用高德天气类工具
- 未绑定高德工具时：天气只用 query_weather
回复不要使用 markdown 标题符号。"""

# 同一工具累计失败达到该次数后，禁止再进入 call_tools
MAX_TOOL_FAILS = 2
# 整图步数上限，防止空转
RECURSION_LIMIT = 8

_extra_tools: list = []
_extra_tools_loaded = False

class ChatState(TypedDict):
    messages: Annotated[list, add_messages]
    tool_fail_counts: dict[str, int]

async def ensure_chat_tools():
    """懒加载高德等额外工具（进程内只拉一次）。"""
    global _extra_tools, _extra_tools_loaded
    if _extra_tools_loaded:
        return
    from app.agents.amap_mcp import get_amap_tools

    _extra_tools = await get_amap_tools()
    _extra_tools_loaded = True


def _build_llm():
    return init_chat_model(
        base_url=settings.AIROBOT_LLM_BASE_URL,
        api_key=settings.AIROBOT_LLM_API_KEY,
        model=settings.AIROBOT_LLM_MODEL,
        model_provider=settings.provider,
    )


def _ensure_error_payload(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return f"{TOOL_ERROR_PREFIX} 工具返回为空"
    if s.startswith(TOOL_ERROR_PREFIX):
        return s
    return f"{TOOL_ERROR_PREFIX} {s}"


def _wrap_tool(fn: Callable[..., str], name: str) -> Callable[..., str]:
    """异常与已带失败语义的返回，统一成 [TOOL_ERROR] 观察结果。"""
    sig = inspect.signature(fn)

    @functools.wraps(fn)
    def _inner(*args: Any, **kwargs: Any) -> str:
        try:
            out = fn(*args, **kwargs)
            text = str(out) if out is not None else ""
            text = text.strip()
            if not text:
                return _ensure_error_payload("")
            # weather / 其它工具若已返回 [TOOL_ERROR]，原样（或补前缀）传出
            if text.startswith(TOOL_ERROR_PREFIX):
                return text
            return text
        except Exception as e:
            return (
                f"{TOOL_ERROR_PREFIX} 工具 {name} 执行异常："
                f"{type(e).__name__}: {e}"
            )

    _inner.__signature__ = sig  # type: ignore[attr-defined]
    return _inner


def _chat_tools() -> list:
    return [
        StructuredTool.from_function(
            func=_wrap_tool(query_order, "query_order"),
            name="query_order",
            description=(
                "查询订单状态与物流。参数 message 为用户原话或订单号（6 位以上数字）。"
                f"失败时返回以 {TOOL_ERROR_PREFIX} 开头的说明。"
            ),
            handle_tool_error=True,
        ),
        StructuredTool.from_function(
            func=_wrap_tool(query_weather, "query_weather"),
            name="query_weather",
            description=(
                "查询实时天气。参数 location 为城市拼音/中文名/经纬度，"
                "如 beijing、杭州、116.40,39.90。"
                f"失败时返回以 {TOOL_ERROR_PREFIX} 开头的说明，必须据此回复用户。"
            ),
            handle_tool_error=True,
        ),
        *_extra_tools,
    ]


async def call_model(state: ChatState) -> dict:
    llm = _build_llm()
    tools = _chat_tools()
    model = llm.bind_tools(tools)
    messages = [SystemMessage(content=CHAT_REACT_SYSTEM)] + list(state["messages"])
    response = await model.ainvoke(messages)
    return {"messages": [response]}


def _bump_fail_count(counts: dict[str, int], name: str, content: str) -> None:
    if str(content).startswith(TOOL_ERROR_PREFIX):
        counts[name] = counts.get(name, 0) + 1
    else:
        counts[name] = 0


async def call_tools(state: ChatState) -> dict:
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    if not tool_calls:
        return {}

    tools_by_name = {t.name: t for t in _chat_tools()}
    outs: list[ToolMessage] = []
    counts = dict(state.get("tool_fail_counts") or {})

    for tc in tool_calls:
        name = tc["name"] if isinstance(tc, dict) else tc.name
        args = dict((tc["args"] if isinstance(tc, dict) else tc.args) or {})
        tid = tc["id"] if isinstance(tc, dict) else tc.id
        tool = tools_by_name.get(name)

        if tool is None:
            content = f"{TOOL_ERROR_PREFIX} 未知工具: {name}"
        else:
            try:
                # MCP 工具仅支持 async，统一 ainvoke（本地 StructuredTool 也可）
                content = await tool.ainvoke(args)
            except Exception as e:
                content = f"{TOOL_ERROR_PREFIX} 工具 {name} 异常: {e}"
            content = str(content)

        _bump_fail_count(counts, name, content)
        outs.append(ToolMessage(content=content, tool_call_id=tid, name=name))

    return {"messages": outs, "tool_fail_counts": counts}


def should_continue(state: ChatState) -> str:
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    if not tool_calls:
        return "end"

    counts = state.get("tool_fail_counts") or {}
    for tc in tool_calls:
        name = tc["name"] if isinstance(tc, dict) else tc.name
        if counts.get(name, 0) >= MAX_TOOL_FAILS:
            return "end"
    return "tools"


def build_chat_graph():
    g = StateGraph(ChatState)
    g.add_node("call_model", call_model)
    g.add_node("call_tools", call_tools)
    g.add_edge(START, "call_model")
    g.add_conditional_edges(
        "call_model",
        should_continue,
        {"tools": "call_tools", "end": END},
    )
    g.add_edge("call_tools", "call_model")
    return g.compile()


chat_graph = build_chat_graph()

async def main():
    await ensure_chat_tools()
    r = await chat_graph.ainvoke(
        {
            "messages": [HumanMessage(content="北京有什么景点")],
            "tool_fail_counts": {},
        },
        config={"recursion_limit": RECURSION_LIMIT},
    )
    return r

if __name__ == "__main__":
    from langchain_core.messages import HumanMessage
    from rich import print as rprint
    import asyncio

    res = asyncio.run(main())
    for m in res["messages"]:
        rprint(m)
