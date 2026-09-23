from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agents.alarm import is_alarm_message
from app.services.chat import classify_intent


@dataclass
class RouteDecision:
    """路由结果：该交给哪个 Agent。"""

    agent_id: str  # "chat" | "knowledge" | "alarm"
    reason: str = ""
    confidence: float | None = None


def _to_agent_id(intent: Any) -> str:
    value = getattr(intent, "value", intent)
    if value in ("alarm", "knowledge", "chat"):
        return str(value)
    # order / unknown / 其它 → 闲聊
    return "chat"


async def classify(
    input: str,
    *,
    history: list | None = None,
    agent_id: str | None = None,
) -> RouteDecision:
    """文本 → RouteDecision。

    - 已填 agent_id：跳过分类
    - is_alarm_message：强判 alarm
    - 否则复用 services.chat.classify_intent
    """
    if agent_id:
        return RouteDecision(
            agent_id=agent_id,
            reason="preset",
            confidence=1.0,
        )
    if is_alarm_message(input):
        return RouteDecision(
            agent_id="alarm",
            reason="is_alarm_message",
            confidence=1.0,
        )
    intent = await classify_intent(input, history or [])
    return RouteDecision(
        agent_id=_to_agent_id(intent),
        reason="classify_intent",
        confidence=None,
    )


class Router:
    """可选面向对象入口；与模块级 classify 行为相同。"""

    async def classify(
        self,
        input: str,
        *,
        history: list | None = None,
        agent_id: str | None = None,
    ) -> RouteDecision:
        return await classify(input, history=history, agent_id=agent_id)
