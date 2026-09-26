from __future__ import annotations

from typing import Any, AsyncIterator

from app.harness.contracts import (
    MODEL_TOKEN,
    RUN_COMPLETED,
    WORKFLOW_STEP,
    RunContext,
    RunEvent,
)
from app.services.chat import _ensure_session_id, run_astream


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
        session_id = _ensure_session_id(ctx.request.session_id)
        # 回写，便于 harness_runs 落库带上真实 session_id
        try:
            ctx.request.session_id = session_id
        except Exception:
            pass
        user_id = options.get("user_id")
        async for chunk in run_astream(
            ctx.request.input,
            session_id,
            options.get("kb"),
            options.get("db"),
            user_id=user_id if isinstance(user_id, str) else None,
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
