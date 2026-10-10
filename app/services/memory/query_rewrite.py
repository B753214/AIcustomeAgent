"""M6-RAG：有历史时把追问改写成可独立检索的问句；失败回退原问句。"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.harness.model import get_light_llm

logger = logging.getLogger("airobot.memory")

_PROMPT_SYSTEM = (
    "你是一个专业的查询重写器。根据历史对话，把当前问题改写为一条可独立检索的中文问句。"
    "只输出问句本身，不要解释。"
)


def _role_content(m: Any) -> tuple[str, str]:
    """兼容 dict 历史与 LangChain Message。"""
    if isinstance(m, dict):
        role = str(m.get("role") or "")
        content = m.get("content") or ""
    else:
        role = str(getattr(m, "type", None) or getattr(m, "role", "") or "")
        content = getattr(m, "content", "") or ""
    if not isinstance(content, str):
        content = str(content)
    return role, content


async def rewrite_retrieval_query(question: str, history: list[Any] | None) -> str:
    """根据历史重写检索查询；无历史/关开关/失败时返回原问句。"""
    if not settings.rag_query_rewrite_enabled:
        return question
    if not history or not (question or "").strip():
        return question

    try:
        hist = "\n".join(
            f"{role}: {content}" for role, content in (_role_content(m) for m in history[-6:])
        )
        resp = await get_light_llm().ainvoke(
            [
                SystemMessage(content=_PROMPT_SYSTEM),
                HumanMessage(
                    content=(
                        f"历史：\n{hist}\n\n"
                        f"当前问题：{question}\n"
                        "请重写为一条可检索问句："
                    )
                ),
            ]
        )
        text = (getattr(resp, "content", None) or "").strip()
        return text or question
    except Exception as e:
        logger.warning("query rewrite failed: %s", e)
        return question
