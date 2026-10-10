from __future__ import annotations

from typing import Any, AsyncIterator

from app.harness.contracts import (
    MODEL_TOKEN,
    RUN_COMPLETED,
    WORKFLOW_STEP,
    RunContext,
    RunEvent,
)
from app.services.chat import harness_run_astream


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
    """包装 harness_run_astream；把 chunk 翻译成标准 RunEvent。"""

    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        options = ctx.request.options or {}
        token = ctx.cancellation_token
        raw_uid = options.get("user_id")
        user_id = raw_uid if isinstance(raw_uid, str) else None

        async for chunk in harness_run_astream(
            ctx.request.input,
            ctx.request.session_id,
            options.get("kb"),
            options.get("db"),
            user_id=user_id,
            run_id=ctx.run_id,
            message_engine="harness",
            session_factory=options.get("session_factory"),
        ):
            if token is not None and token.is_cancelled():
                return
            # 落库用的真实 session_id（归属确认后可能换号）
            sid = (chunk.get("meta") or {}).get("session_id")
            if sid:
                try:
                    ctx.request.session_id = sid
                except Exception:
                    pass
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
