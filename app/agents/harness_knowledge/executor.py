from __future__ import annotations

from typing import Any, AsyncIterator

from app.config import settings
from app.harness.contracts import RUN_COMPLETED, RUN_FAILED, RunContext, RunEvent
from app.rag.retriever import aanswer_with_rag


async def _history_for_run(ctx: RunContext) -> list[Any] | None:
    """优先用 options.history；否则按 session 装配 RAG 独立预算的上下文。"""
    options = ctx.request.options or {}
    if "history" in options:
        return options.get("history")

    session_id = ctx.request.session_id
    factory = options.get("session_factory")
    db = options.get("db")
    user_id = options.get("user_id")
    if not session_id or (factory is None and db is None):
        return None

    from app.services.chat import (
        _db_scope,
        _prepare_history,
        _resolve_owned_session,
        _to_langchain_messages,
    )

    async with _db_scope(db, factory) as scoped:
        session_id, uid = await _resolve_owned_session(session_id, user_id, scoped)
        history = await _prepare_history(
            session_id,
            uid,
            scoped,
            ctx.request.input,
            create_if_missing=False,
            context_token_budget=settings.rag_history_token_budget,
        )
    return _to_langchain_messages(history)


class KnowledgeExecutor:
    """包装现有 aanswer_with_rag；只产出标准 RunEvent。"""

    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        options = ctx.request.options or {}
        kb = options.get("kb")
        try:
            history = await _history_for_run(ctx)
            answer, sources = await aanswer_with_rag(
                ctx.request.input,
                kb,
                history=history,
                session_factory=options.get("session_factory"),
            )
            yield RunEvent(
                type=RUN_COMPLETED,
                run_id=ctx.run_id,
                sequence=1,
                payload={
                    "output": answer or "",
                    "sources": sources or [],
                    "metadata": {
                        "intent": "knowledge",
                        "engine": "langchain",
                    },
                },
            )
        except Exception as e:
            yield RunEvent(
                type=RUN_FAILED,
                run_id=ctx.run_id,
                sequence=1,
                payload={
                    "message": str(e),
                },
            )
