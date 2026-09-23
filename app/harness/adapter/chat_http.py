from __future__ import annotations

from app.database import AsyncSession
from app.harness.contracts import RunRequest, RunResult
from app.harness.registry import get_builtin_agent_registry
from app.harness.routing import classify
from app.harness.runtime import AgentRuntime
from app.rag.retriever import KnowledgeBase
from app.schemas import ChatRequest, ChatResponse


def to_run_request(
    req: ChatRequest,
    kb: KnowledgeBase | None = None,
    db: AsyncSession | None = None,
    *,
    agent_id: str = "chat",
    route: dict | None = None,
) -> RunRequest:
    """HTTP ChatRequest → Harness RunRequest。"""
    options: dict = {
        "kb": kb,
        "db": db,
    }
    if route:
        options["route"] = route
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
    db: AsyncSession,
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
