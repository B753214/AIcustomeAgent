"""Token 估算：优先 tiktoken(cl100k_base)，失败则中文近似。"""
from __future__ import annotations

from typing import Any

_enc = None
_enc_failed = False


def _encoding():
    """懒加载并缓存 tiktoken encoding。"""
    global _enc, _enc_failed
    if _enc_failed:
        return None
    if _enc is None:
        try:
            import tiktoken

            _enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _enc_failed = True
            return None
    return _enc


def _fallback_estimate(text: str) -> int:
    """无 tiktoken 时：按字符近似（偏中文场景）。"""
    t = text or ""
    if not t:
        return 0
    return max(1, (len(t) + 1) // 2)


def estimate_text(text: str) -> int:
    """估计文本的 token 数量。"""
    t = text or ""
    if not t:
        return 0
    enc = _encoding()
    if enc is None:
        return _fallback_estimate(t)
    try:
        return len(enc.encode(t))
    except Exception:
        return _fallback_estimate(t)


def estimate_messages(messages: list[dict[str, Any]] | None) -> int:
    """估计消息列表 token：每条 role+content，另加少量格式开销。"""
    total = 0
    for m in messages or []:
        role = str(m.get("role") or "")
        content = str(m.get("content") or "")
        total += estimate_text(f"{role}: {content}")
        total += 4
    return total
