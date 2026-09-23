from __future__ import annotations

from typing import AsyncIterator

from app.harness.contracts import RUN_COMPLETED, RUN_FAILED, RunContext, RunEvent
from app.rag.retriever import aanswer_with_rag


class KnowledgeExecutor:
    """包装现有 aanswer_with_rag；只产出标准 RunEvent。"""

    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        options = ctx.request.options or {}
        kb = options.get("kb")
        try:
            answer, sources = await aanswer_with_rag(
                ctx.request.input,
                kb,
                history=options.get("history"),
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
