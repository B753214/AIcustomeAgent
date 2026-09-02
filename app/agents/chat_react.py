"""闲聊入口：手写 StateGraph（chat_graph）；对外返回形状不变。"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.agents.chat_graph import RECURSION_LIMIT, TOOL_ERROR_PREFIX, chat_graph, ensure_chat_tools

_FALLBACK = "我这边暂时没法查到，你可以再发一下订单号，或问问某城市的天气。"


def _message_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            else:
                text = getattr(block, "text", None)
                if text:
                    parts.append(str(text))
        return "".join(parts)
    return str(content)


def _collect_tool_names(messages: list) -> list[str]:
    names: list[str] = []
    for msg in messages:
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            if isinstance(tc, dict):
                name = tc.get("name") or ""
            else:
                name = getattr(tc, "name", "") or ""
            if name:
                names.append(name)
        if isinstance(msg, ToolMessage):
            n = getattr(msg, "name", None) or ""
            if n:
                names.append(n)
    return names


def _collect_tool_errors(messages: list) -> list[str]:
    """从 ToolMessage 中收集 [TOOL_ERROR] 观察结果，供 meta 与兜底回复。"""
    errors: list[str] = []
    for msg in messages:
        if not isinstance(msg, ToolMessage) and getattr(msg, "type", None) != "tool":
            continue
        text = _message_text(getattr(msg, "content", None)).strip()
        if text.startswith(TOOL_ERROR_PREFIX):
            errors.append(text)
        elif text.lower().startswith("error:") or "error invoking tool" in text.lower():
            errors.append(f"{TOOL_ERROR_PREFIX} {text}")
    return errors


def _last_ai_text(messages: list) -> str:
    for msg in reversed(messages or []):
        if isinstance(msg, AIMessage) or getattr(msg, "type", None) == "ai":
            tool_calls = getattr(msg, "tool_calls", None) or []
            text = _message_text(getattr(msg, "content", None))
            if text.strip():
                return text
            if tool_calls:
                continue
    if messages:
        return _message_text(getattr(messages[-1], "content", messages[-1]))
    return ""


def _filter_history(history: list | None) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for m in history or []:
        if getattr(m, "type", None) == "system" or m.__class__.__name__ == "SystemMessage":
            continue
        out.append(m)
    return out


def _finalize_reply(reply: str, tool_errors: list[str]) -> str:
    """若模型没产出有效回复，但工具已报错，直接把错误观察给用户。"""
    text = (reply or "").strip()
    if text:
        return text
    if tool_errors:
        last = tool_errors[-1]
        return last.replace(TOOL_ERROR_PREFIX, "", 1).strip() or _FALLBACK
    return _FALLBACK


def _intent_from_tools(tools_used: list[str]) -> str:
    # 天气仍归 chat，与 IntentEnum / 前端契约一致；订单单独标 order
    if "query_order" in tools_used and "query_weather" not in tools_used:
        return "order"
    return "chat"


async def run_chat_react(
    message: str,
    history: list | None = None,
) -> dict:
    """返回 {reply, intent, sources, engine, meta}。失败时降级文案，不抛。"""
    tools_used: list[str] = []
    tool_errors: list[str] = []
    try:
        await ensure_chat_tools()
        messages: list = _filter_history(history)
        messages.append(HumanMessage(content=message))
        result = await chat_graph.ainvoke(
            {"messages": messages, "tool_fail_counts": {}},
            config={"recursion_limit": RECURSION_LIMIT},
        )
        out_msgs = list(result.get("messages") or [])
        tools_used = _collect_tool_names(out_msgs)
        tool_errors = _collect_tool_errors(out_msgs)
        reply = _finalize_reply(_last_ai_text(out_msgs), tool_errors)
        return {
            "reply": reply,
            "intent": _intent_from_tools(tools_used),
            "sources": [],
            "engine": "chat_react",
            "cache_hit": False,
            "meta": {
                "tool_calls": tools_used,
                "tool_errors": tool_errors,
                "tool_failed": bool(tool_errors),
                "tool_fail_counts": dict(result.get("tool_fail_counts") or {}),
            },
        }
    except Exception as e:
        print(f"[chat_react] 失败，降级: {e}")
        return {
            "reply": _FALLBACK,
            "intent": "chat",
            "sources": [],
            "engine": "chat_react",
            "cache_hit": False,
            "meta": {
                "tool_calls": tools_used,
                "tool_errors": tool_errors,
                "tool_failed": True,
                "error": str(e),
            },
        }


async def iter_chat_react(message: str, history: list | None = None):
    """SSE：astream_events 推送 tool stage + LLM token 流，最后 result。"""
    yield {"type": "stage", "stage": "chat_react", "msg": "客服助手处理中…", "ok": True}
    messages = _filter_history(history)
    messages.append(HumanMessage(content=message))
    state = {"messages": messages, "tool_fail_counts": {}}
    final_msgs = list(messages)
    tool_fail_counts: dict = {}
    tool_round_done = False
    streamed_any = False
    from rich import print as rprint
    model_buffer: list[str] = []
    try:
        await ensure_chat_tools()
        async for ev in chat_graph.astream_events(
            state,
            config={"recursion_limit": RECURSION_LIMIT},
            version="v2",
        ):
            kind = ev.get("event")
            rprint(f"[chat_react] {kind}: {ev.get('name')}")
            rprint("ev:", ev)
            if kind == "on_chat_model_stream":
                chunk = (ev.get("data") or {}).get("chunk")
                content = getattr(chunk, "content", "") if chunk is not None else ""
                piece = content if isinstance(content, str) else ""
                if not piece:
                    continue
                if tool_round_done:
                    streamed_any = True
                    yield {"type": "token", "content": piece}
                else:
                    model_buffer.append(piece)
                continue

            if kind == "on_chat_model_end":
                output = (ev.get("data") or {}).get("output")
                if getattr(output, "tool_calls", None):
                    model_buffer.clear()
                elif not tool_round_done and model_buffer:
                    for piece in model_buffer:
                        streamed_any = True
                        yield {"type": "token", "content": piece}
                    model_buffer.clear()
                continue

            if kind != "on_chain_end":
                continue

            name = ev.get("name") or ""
            output = (ev.get("data") or {}).get("output")
            if not isinstance(output, dict):
                continue

            if name == "call_model":
                if "messages" in output:
                    final_msgs.extend(output["messages"])
                continue

            if name != "call_tools":
                continue

            tool_round_done = True
            model_buffer.clear()
            if "messages" in output:
                final_msgs.extend(output["messages"])
            if "tool_fail_counts" in output:
                tool_fail_counts = dict(output["tool_fail_counts"] or {})

            tool_msgs = output.get("messages") or []
            names = _collect_tool_names(tool_msgs)
            if names:
                yield {
                    "type": "stage",
                    "stage": "tool",
                    "msg": "调用 " + ", ".join(dict.fromkeys(names)),
                    "ok": True,
                }
            errs = _collect_tool_errors(tool_msgs)
            if errs:
                yield {
                    "type": "stage",
                    "stage": "tool_error",
                    "msg": "工具返回错误，已交由模型处理或降级展示",
                    "ok": False,
                }

        tools_used = _collect_tool_names(final_msgs)
        tool_errors = _collect_tool_errors(final_msgs)
        reply = _finalize_reply(_last_ai_text(final_msgs), tool_errors)
        res = {
            "reply": reply,
            "intent": _intent_from_tools(tools_used),
            "sources": [],
            "engine": "chat_react",
            "cache_hit": False,
            "meta": {
                "tool_calls": tools_used,
                "tool_errors": tool_errors,
                "tool_failed": bool(tool_errors),
                "tool_fail_counts": tool_fail_counts,
            },
        }
        if reply and not streamed_any:
            yield {"type": "token", "content": reply}
        yield {"type": "result", **res}

    except Exception as e:
        print(f"[iter_chat_react] 失败: {e}")
        yield {"type": "token", "content": _FALLBACK}
        yield {
            "type": "result",
            "reply": _FALLBACK,
            "intent": "chat",
            "sources": [],
            "engine": "chat_react",
            "cache_hit": False,
            "meta": {
                "tool_calls": [],
                "tool_errors": [],
                "tool_failed": True,
                "error": str(e),
            },
        }

async def main(message: str, history: list | None = None):
    async for ev in iter_chat_react(message, history):
        print(ev)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main("查订单 888888"))
