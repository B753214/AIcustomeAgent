from __future__ import annotations

from typing import AsyncIterator

from app.harness.contracts import RUN_COMPLETED, RunContext, RunEvent
from app.services.chat import run


class ChatExecutor:
    """包装现有 services.chat.run；只产出标准 RunEvent。"""

    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        options = ctx.request.options or {}
        res = await run(
            ctx.request.input,
            ctx.request.session_id or "default",
            options.get("kb"),
            options.get("db"),
        )
        meta = dict(res.get("meta") or {})
        yield RunEvent(
            type=RUN_COMPLETED,
            run_id=ctx.run_id,
            sequence=1,
            payload={
                "output": res.get("reply") or "",
                "sources": res.get("sources") or [],
                "metadata": {
                    "intent": res.get("intent"),
                    "engine": res.get("engine"),
                    "cache_hit": res.get("cache_hit", False),
                    "used_crew": res.get("used_crew", False),
                    **meta,
                },
            },
        )
