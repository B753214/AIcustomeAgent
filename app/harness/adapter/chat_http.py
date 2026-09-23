from __future__ import annotations

from typing import AsyncIterator

from app.harness.contracts import (
    RUN_COMPLETED,
    RunContext,
    RunEvent,
    RunRequest,
    RunResult,
)
from app.harness.runtime import AgentRuntime
from app.schemas import ChatRequest, ChatResponse


def to_run_request(req: ChatRequest) -> RunRequest:
    """HTTP ChatRequest → Harness RunRequest。"""
    return RunRequest(
        input=req.message,
        session_id=req.session_id,
        agent_id="chat",  # H2 先写死；H4 再接 Router
        caller="api",
    )


def _sources_for_chat(result: RunResult) -> list:
    out: list = []
    for item in result.sources or []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            out.append(item.get("title") or item.get("uri") or str(item))
        else:
            out.append(str(item))
    return out


def to_chat_response(result: RunResult) -> ChatResponse:
    """Harness RunResult → 旧 ChatResponse（兼容现有客户端）。"""
    meta = dict(result.metadata or {})
    if result.error:
        meta["error"] = result.error
    if result.usage:
        meta["usage"] = result.usage

    return ChatResponse(
        reply=result.output or "",
        intent=meta.get("intent"),
        sources=_sources_for_chat(result),
        engine=meta.get("engine", "harness"),
        used_crew=bool(meta.get("used_crew", False)),
        cache_hit=bool(meta.get("cache_hit", False)),
        meta=meta,
    )


class EchoExecutor:
    """H2-3 占位执行器；H4 换成 ChatExecutor。"""

    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        yield RunEvent(
            type=RUN_COMPLETED,
            run_id=ctx.run_id,
            sequence=1,
            payload={
                "output": f"harness:{ctx.request.input}",
                "metadata": {"engine": "harness", "intent": None},
            },
        )


def build_chat_runtime() -> AgentRuntime:
    return AgentRuntime(EchoExecutor())


async def chat_harness_http(req: ChatRequest) -> ChatResponse:
    """JSON chat：走 Runtime（开关打开时由 main 调用）。"""
    result = await build_chat_runtime().execute(to_run_request(req))
    return to_chat_response(result)
