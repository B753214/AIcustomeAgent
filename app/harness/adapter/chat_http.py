from __future__ import annotations

from typing import AsyncIterator

from app.database import AsyncSession as session_factory
from app.harness.contracts import RunEvent, RunRequest, RunResult
from app.harness.registry import get_builtin_agent_registry
from app.harness.routing import classify
from app.harness.runtime import AgentRuntime
from app.harness.runtime.cancellation import CancellationToken
from app.rag.retriever import KnowledgeBase
from app.schemas import ChatRequest, ChatResponse

# database.AsyncSession 实际是 async_sessionmaker，兼作类型占位与 session_factory
AsyncSession = session_factory


def to_run_request(
    req: ChatRequest,
    kb: KnowledgeBase | None = None,
    db: object | None = None,
    *,
    agent_id: str = "chat",
    route: dict | None = None,
    cancellation_token: CancellationToken | None = None,
) -> RunRequest:
    """HTTP ChatRequest → Harness RunRequest。"""
    options: dict = {
        "kb": kb,
        "db": db,
        "session_factory": session_factory,
    }
    if route:
        options["route"] = route
    if cancellation_token is not None:
        options["cancellation_token"] = cancellation_token
    return RunRequest(
        input=req.message,
        session_id=req.session_id,
        agent_id=agent_id,
        caller="api",
        options=options,
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


def build_chat_runtime(agent_id: str) -> AgentRuntime:
    """按 agent_id 从内置 Registry 取 Executor；未知 id 回退 chat。"""
    registry = get_builtin_agent_registry()
    resolved = agent_id if agent_id in registry.list_ids() else "chat"
    defn = registry.get(resolved)
    return AgentRuntime(defn.executor)


async def chat_harness_http(
    req: ChatRequest,
    kb: KnowledgeBase,
    db: object,
) -> ChatResponse:
    """JSON chat：先 Router，再按 agent_id 选 Executor 跑 Runtime。"""
    decision = await classify(req.message)
    run_req = to_run_request(
        req,
        kb,
        db,
        agent_id=decision.agent_id,
        route={
            "reason": decision.reason,
            "confidence": decision.confidence,
        },
    )
    result = await build_chat_runtime(decision.agent_id).execute(run_req)
    return to_chat_response(result)


def run_event_to_sse_dict(ev: RunEvent) -> dict | None:
    """标准 RunEvent → 旧版 SSE chunk dict；不需要推送的返回 None。"""
    if ev.type == "run.started":
        return None
    if ev.type == "model.token":
        return {"type": "token", "content": ev.payload.get("content") or ""}
    if ev.type == "workflow.step":
        return {
            "type": "stage",
            "stage": ev.payload.get("stage"),
            "msg": ev.payload.get("message"),
            "ok": ev.payload.get("ok"),
            "ms": ev.payload.get("ms"),
        }
    if ev.type == "run.completed":
        meta = dict(ev.payload.get("metadata") or {})
        return {
            "type": "done",
            "run_id": ev.run_id,
            "reply": ev.payload.get("output") or "",
            "sources": ev.payload.get("sources") or [],
            "intent": meta.get("intent"),
            "engine": meta.get("engine"),
            "cache_hit": meta.get("cache_hit", False),
        }
    if ev.type == "run.failed":
        return {
            "type": "error",
            "run_id": ev.run_id,
            "message": (ev.payload or {}).get("message") or "run failed",
        }
    return None


async def chat_harness_stream(
    req: ChatRequest,
    kb: KnowledgeBase,
    db: object,
    *,
    cancellation_token: CancellationToken | None = None,
) -> AsyncIterator[dict]:
    """流式聊天：Router → Runtime.execute_stream → 旧版 SSE chunk（dict）。"""
    token = cancellation_token or CancellationToken()
    decision = await classify(req.message)
    run_req = to_run_request(
        req,
        kb,
        db,
        agent_id=decision.agent_id,
        route={
            "reason": decision.reason,
            "confidence": decision.confidence,
        },
        cancellation_token=token,
    )
    runtime = build_chat_runtime(decision.agent_id)
    async for ev in runtime.execute_stream(run_req):
        frame = run_event_to_sse_dict(ev)
        if frame is not None:
            yield frame
