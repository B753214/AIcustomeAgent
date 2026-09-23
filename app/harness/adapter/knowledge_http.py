from __future__ import annotations

from app.agents.harness_knowledge.executor import KnowledgeExecutor
from app.harness.contracts import RunRequest, RunResult
from app.harness.runtime import AgentRuntime
from app.rag.retriever import KnowledgeBase


def to_run_request(query: str, kb: KnowledgeBase) -> RunRequest:
    """HTTP query → Harness RunRequest。"""
    return RunRequest(
        input=query,
        agent_id="knowledge",
        caller="api",
        options={"kb": kb},
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
    return AgentRuntime(KnowledgeExecutor())


async def knowledge_harness_http(query: str, kb: KnowledgeBase) -> dict:
    """JSON retrieval：走 Runtime（开关打开时由 main 调用）。"""
    result = await build_knowledge_runtime().execute(to_run_request(query, kb))
    return to_retrieval_response(result)
