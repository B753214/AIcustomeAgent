from __future__ import annotations

from app.database import AsyncSession as session_factory
from app.harness.contracts import RunRequest, RunResult
from app.harness.registry import get_builtin_agent_registry, register_default_policies
from app.harness.runtime import AgentRuntime
from app.rag.retriever import KnowledgeBase


def to_run_request(query: str, kb: KnowledgeBase) -> RunRequest:
    """HTTP query → Harness RunRequest。"""
    return RunRequest(
        input=query,
        agent_id="knowledge",
        caller="api",
        options={"kb": kb, "session_factory": session_factory},
    )


def to_retrieval_response(result: RunResult) -> dict:
    """Harness RunResult → 旧 /retrieval 响应形状。"""
    sources: list = []
    for item in result.sources or []:
        if isinstance(item, str):
            sources.append(item)
        elif isinstance(item, dict):
            sources.append(item.get("title") or item.get("uri") or str(item))
        else:
            sources.append(str(item))
    out: dict = {
        "reply": result.output or "",
        "sources": sources,
    }
    if result.error:
        out["error"] = result.error
    return out


def build_knowledge_runtime() -> AgentRuntime:
    defn = get_builtin_agent_registry().get("knowledge")
    return AgentRuntime(
        defn.executor,
        policy_registry=register_default_policies(),
        policy_set=defn.policy_set or "default",
        tool_allowlist=list(defn.tool_allowlist),
        budget=defn.budget,
    )



async def knowledge_harness_http(query: str, kb: KnowledgeBase) -> dict:
    """JSON retrieval：走 Runtime（开关打开时由 main 调用）。"""
    result = await build_knowledge_runtime().execute(to_run_request(query, kb))
    return to_retrieval_response(result)
