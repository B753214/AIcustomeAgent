"""长期事实可写性判定（M4-1）；抽取/落库见 M4-2+。"""
from __future__ import annotations

from typing import Any, Literal

Decision = Literal["reject", "candidate", "active"]

FACT_KINDS = frozenset({"profile", "preference", "constraint", "business_fact"})
SOURCE_TYPES = frozenset({"explicit", "inferred", "imported"})

# 内容侧硬禁止关键词（小写匹配）；覆盖天气/临时订单/验证码等
_REJECT_CONTENT_MARKERS = (
    "天气",
    "气温",
    "下雨",
    "预报",
    "物流状态",
    "运单",
    "验证码",
    "验证码是",
    "password",
    "密码",
    "token",
    "cookie",
    "身份证",
    "护照",
)

_REJECT_KEY_MARKERS = (
    "weather",
    "order_status",
    "tracking_status",
    "otp",
    "verify_code",
    "password",
    "api_key",
    "access_token",
)

# 推断类默认置信阈值：低于此只能 reject 或强制 candidate（本函数对 inferred 一律 candidate）
DEFAULT_ACTIVE_MIN_CONFIDENCE = 0.7


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def should_persist_fact(
    *,
    kind: str,
    normalized_key: str,
    content: str,
    source_type: str = "inferred",
    confidence: float = 0.5,
    sensitive: bool = False,
) -> tuple[bool, Decision, str]:
    """判断候选事实是否可进 memory_facts，以及建议初始 status。

    返回：(可写入, 建议 status 或 reject 时的占位, 原因)
    - reject → 第一项 False，第二项 "reject"
    - 可写 → True + "candidate" | "active"
    """
    kind_n = _norm(kind)
    source_n = _norm(source_type)
    key_n = _norm(normalized_key)
    content_n = _norm(content)

    if kind_n not in FACT_KINDS:
        return False, "reject", f"unknown kind: {kind}"
    if source_n not in SOURCE_TYPES:
        return False, "reject", f"unknown source_type: {source_type}"
    if not key_n or not content_n:
        return False, "reject", "empty key or content"

    for m in _REJECT_KEY_MARKERS:
        if m in key_n:
            return False, "reject", f"forbidden key marker: {m}"
    for m in _REJECT_CONTENT_MARKERS:
        if m in content_n:
            return False, "reject", f"forbidden content marker: {m}"

    if sensitive:
        if source_n == "inferred":
            return False, "reject", "sensitive inferred fact forbidden"
        return True, "candidate", "sensitive → candidate only"

    if source_n == "inferred":
        return True, "candidate", "inferred → candidate (needs confirm)"

    if source_n == "imported":
        return True, "candidate", "imported → candidate until audit"

    # explicit
    if confidence < DEFAULT_ACTIVE_MIN_CONFIDENCE:
        return True, "candidate", "explicit but low confidence → candidate"
    return True, "active", "explicit high confidence → active"


def decide_initial_status(decision: Decision) -> str | None:
    """reject → None；否则返回 status 字符串。"""
    if decision == "reject":
        return None
    return decision


def classify_fact_payload(payload: dict[str, Any]) -> tuple[bool, Decision, str]:
    """从字典字段判定（便于 M4-2 结构化输出后复用）。"""
    return should_persist_fact(
        kind=str(payload.get("kind") or ""),
        normalized_key=str(payload.get("normalized_key") or ""),
        content=str(payload.get("content") or ""),
        source_type=str(payload.get("source_type") or "inferred"),
        confidence=float(payload.get("confidence") or 0.0),
        sensitive=bool(payload.get("sensitive") or False),
    )
