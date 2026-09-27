"""按 Token 预算裁剪最近对话（M3-2）；摘要注入见 M3-4。"""
from __future__ import annotations

from typing import Any

from app.config import settings
from app.schema.memory_summary import SessionSummaryPayload
from app.services.memory.token_estimate import estimate_messages, estimate_text

# 预留给 system / 工具说明等，不把预算吃满
_SYSTEM_RESERVE_TOKENS = 200


def build_recent_context(
    history: list[dict[str, Any]] | None,
    *,
    current_message: str = "",
    budget: int | None = None,
    max_turns: int | None = None,
    system_reserve: int = _SYSTEM_RESERVE_TOKENS,
    summary: SessionSummaryPayload | None = None,
    facts_block: str | None = None,
) -> list[dict[str, Any]]:
    """从旧到新裁掉超预算消息；不修改调用方传入的 list。

    - 主限制：estimate_messages(prefix + selected) <= remaining
    - 辅限制：无摘要时先只保留最近 max_turns 轮；有摘要时 recent 已由上游 keep_turns 切好
    - 摘要块 + 长期事实块前置，裁剪只丢原文
    """
    selected = list(history or [])
    if budget is None:
        budget = settings.memory_context_token_budget
    if max_turns is None:
        max_turns = settings.memory_max_turns

    if summary is None and max_turns and max_turns > 0:
        selected = selected[-(max_turns * 2) :]

    prefix: list[dict[str, Any]] = []
    if summary is not None:
        from app.services.memory.summary_service import format_summary

        prefix.append({"role": "system", "content": format_summary(summary)})
    if facts_block:
        prefix.append({"role": "system", "content": facts_block})

    remaining = int(budget) - estimate_text(current_message or "") - max(0, system_reserve)
    remaining = max(0, remaining)

    while selected and estimate_messages(prefix + selected) > remaining:
        selected.pop(0)

    return prefix + selected
