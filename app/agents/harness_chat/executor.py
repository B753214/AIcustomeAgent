from __future__ import annotations

from typing import Any, AsyncIterator

from app.harness.contracts import (
    MODEL_TOKEN,
    RUN_COMPLETED,
    WORKFLOW_STEP,
    RunContext,
    RunEvent,
)
from app.services.chat import run_astream


def _meta_from_done(chunk: dict[str, Any]) -> dict[str, Any]:
    meta = dict(chunk.get("meta") or {})
    return {
        "intent": chunk.get("intent"),
        "engine": chunk.get("engine"),
        "cache_hit": chunk.get("cache_hit", False),
        "used_crew": chunk.get("used_crew", False),
        **meta,
    }


class ChatExecutor:
    """包装 services.chat.run_astream；把旧 chunk 翻译成标准 RunEvent。"""

    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        options = ctx.request.options or {}
        token = ctx.cancellation_token
        async for chunk in run_astream(
            ctx.request.input,
            ctx.request.session_id or "default",
            options.get("kb"),
            options.get("db"),
        ):
            if token is not None and token.is_cancelled():
                return
            t = chunk.get("type")
            if t == "token":
                yield RunEvent(
                    type=MODEL_TOKEN,
                    run_id=ctx.run_id,
                    sequence=0,
                    payload={"content": chunk.get("content") or ""},
                )
            elif t == "stage":
                yield RunEvent(
                    type=WORKFLOW_STEP,
                    run_id=ctx.run_id,
                    sequence=0,
                    payload={
                        "stage": chunk.get("stage"),
                        "message": chunk.get("msg"),
                        "ok": chunk.get("ok"),
                        "ms": chunk.get("ms"),
                    },
                )
            elif t == "done":
                yield RunEvent(
                    type=RUN_COMPLETED,
                    run_id=ctx.run_id,
                    sequence=0,
                    payload={
                        "output": chunk.get("reply") or "",
                        "sources": chunk.get("sources") or [],
                        "metadata": _meta_from_done(chunk),
                    },
                )
                return
            # intent 等其它旧事件：跳过（由 stage/done 已覆盖关键信息）
