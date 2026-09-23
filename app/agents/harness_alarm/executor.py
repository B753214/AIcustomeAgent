from __future__ import annotations

from typing import AsyncIterator

from app.agents.alarm.runner import run_alarm_agent
from app.harness.contracts import RUN_COMPLETED, RUN_FAILED, RunContext, RunEvent


class AlarmExecutor:
    """包装现有 run_alarm_agent；只产出标准 RunEvent。"""

    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        try:
            res = await run_alarm_agent(ctx.request.input)
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
                        "engine": res.get("engine", "alarm"),
                        "cache_hit": res.get("cache_hit", False),
                        "skip": res.get("skip", False),
                        **meta,
                    },
                },
            )
        except Exception as e:
            yield RunEvent(
                type=RUN_FAILED,
                run_id=ctx.run_id,
                sequence=1,
                payload={"message": str(e)},
            )
