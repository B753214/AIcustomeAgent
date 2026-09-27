"""本轮对话 → 长期事实（M4-5）：触发条件、降级、挂 chat。"""
from __future__ import annotations

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.memory_facts import MemoryFact
from app.services.memory.fact_extract import extract_and_filter
from app.services.memory.fact_store import persist_prepared_facts

logger = logging.getLogger("airobot.memory")

_FACT_TRIGGER_RE = re.compile(
    r"请记住|记住我|别忘了|我叫|我是|以后请|不要再|我的偏好|请用.+回复",
    re.IGNORECASE,
)


def should_trigger_fact_extract(user_text: str) -> bool:
    """是否对本轮用户句触发抽取。"""
    mode = (settings.memory_fact_trigger_mode or "heuristic").strip().lower()
    if mode == "off":
        return False
    if mode == "always":
        return True
    # heuristic（默认）
    return bool(_FACT_TRIGGER_RE.search(user_text or ""))


async def maybe_persist_facts_from_turn(
    user_id: str,
    user_text: str,
    assistant_text: str,
    db: AsyncSession,
    *,
    tenant_id: str | None = None,
) -> list[MemoryFact]:
    """开关 + 启发式 → 抽取 → 落库；失败返回 []，不抛出。

    auto_active / min_confidence 由 fact_store._resolve_status 在 upsert 时生效：
    False 或低置信时即便 policy 判 active 也落 candidate。
    """
    if not settings.memory_fact_extract_enabled:
        return []
    if not should_trigger_fact_extract(user_text):
        return []
    try:
        messages = [
            {"role": "user", "content": user_text or ""},
            {"role": "assistant", "content": assistant_text or ""},
        ]
        candidates = await extract_and_filter(messages)
        return await persist_prepared_facts(
            user_id, candidates, db, tenant_id=tenant_id
        )
    except Exception as e:
        logger.warning("fact persist failed: %s", e)
        return []
