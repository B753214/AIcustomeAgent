from __future__ import annotations

from typing import Any, AsyncIterator

from app.agents.alarm.runner import run_alarm_agent_stream
from app.agents.harness_alarm.checkpoint import (
    ALARM_AFTER_FETCH,
    ALARM_AFTER_REPLAN,
    ALARM_BEFORE_REPORT,
)
from app.harness.contracts import (
    MODEL_TOKEN,
    RUN_COMPLETED,
    RUN_FAILED,
    WORKFLOW_STEP,
    RunContext,
    RunEvent,
)
from app.harness_storage import persist_checkpoint, persist_load_checkpoint

# 越靠后的步骤优先恢复
_RESUME_NAMES = (
    ALARM_BEFORE_REPORT,
    ALARM_AFTER_REPLAN,
    ALARM_AFTER_FETCH,
)


def _meta_from_done(chunk: dict[str, Any]) -> dict[str, Any]:
    meta = dict(chunk.get("meta") or {})
    return {
        "intent": chunk.get("intent"),
        "engine": chunk.get("engine", "alarm"),
        "cache_hit": chunk.get("cache_hit", False),
        "skip": chunk.get("skip", False),
        **meta,
    }


async def _load_resume(factory: Any, run_id: str) -> dict[str, Any] | None:
    for name in _RESUME_NAMES:
        payload = await persist_load_checkpoint(factory, run_id, name)
        if payload:
            return payload
    return None


class AlarmExecutor:
    """包装 run_alarm_agent_stream；把旧 chunk 翻译成标准 RunEvent。"""

    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        token = ctx.cancellation_token
        factory = (ctx.request.options or {}).get("session_factory")
        resume = await _load_resume(factory, ctx.run_id)

        async def on_checkpoint(name: str, payload: dict) -> None:
            await persist_checkpoint(factory, ctx.run_id, name, payload)

        try:
            async for chunk in run_alarm_agent_stream(
                ctx.request.input,
                resume=resume,
                on_checkpoint=on_checkpoint,
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
                            "meta": chunk.get("meta"),
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
        except Exception as e:
            yield RunEvent(
                type=RUN_FAILED,
                run_id=ctx.run_id,
                sequence=0,
                payload={"message": str(e)},
            )
