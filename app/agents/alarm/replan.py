"""Replan 规则：是否补第 2 页 / 是否换 playbook（纯函数，不接 runner）。"""
from __future__ import annotations

from typing import Any

from app.agents.alarm.classify import SKILL_MAP, classify_by_name

# hint=precise 时必须在明细文案里看到这些，才认为分类可信
_HINT_TRUST_KEYWORDS = (
    "bff",
    "服务端",
    "接口失败",
    "code非1",
    "ajx",
    "ajax",
    "jserror",
    "js错误",
    "白屏",
    "渲染",
    "首屏",
    "voc",
    "舆情",
)


def _as_int(value: Any, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _detail_items(monitor_detail: Any) -> list[dict]:
    if monitor_detail is None:
        return []
    if isinstance(monitor_detail, list):
        raw = monitor_detail
    elif isinstance(monitor_detail, dict):
        lst = monitor_detail.get("list")
        raw = lst if isinstance(lst, list) else []
    else:
        return []
    return [x for x in raw[:20] if isinstance(x, dict)]


def _skill_key_from_meta(meta: dict) -> str:
    return next((k for k, v in SKILL_MAP.items() if v is meta), "precise")


def _build_detail_blob(
    error_analysis: dict,
    monitor_detail: Any = None,
) -> str:
    parts: list[str] = []
    for item in (error_analysis.get("topErrorsRaw") or [])[:5]:
        if isinstance(item, dict) and item.get("msg"):
            parts.append(str(item["msg"]))
    for key in ("pageName", "errUrl", "scene", "errFlag"):
        val = error_analysis.get(key)
        if val:
            parts.append(str(val))
    for row in _detail_items(monitor_detail):
        for key in ("err_msg", "page_name", "url", "scene"):
            val = row.get(key)
            if val:
                parts.append(str(val))
    return " ".join(parts)


def _hint_trusted(hint_key: str, blob: str) -> bool:
    if hint_key != "precise":
        return True
    lower = blob.lower()
    return any(kw.lower() in lower or kw in blob for kw in _HINT_TRUST_KEYWORDS)


def should_fetch_page2(
    *,
    page: int,
    page_size: int = 50,
    fetched_pages: list[int] | None = None,
    monitor_rate: dict | None = None,
    error_analysis: dict | None = None,
    pagination: str | None = None,  # "browser" | "browser_only" | None
    draft_report: dict | None = None,  # 可选：含 evidence / conclusion
) -> bool:
    if page != 1 or 2 in (fetched_pages or []):
        return False

    count = _as_int((monitor_rate or {}).get("count"))
    if count == 0:
        return False

    if not error_analysis:
        return False
    total = _as_int(error_analysis.get("total"), 0) or 0
    if total < page_size:
        return False

    if pagination not in ("browser", "browser_only"):
        return False

    top_raw = error_analysis.get("topErrorsRaw") or []
    if top_raw and total > 0:
        top1 = _as_int(top_raw[0].get("count"), 0) or 0
        if top1 / total < 0.4:
            return True

    unique_users = _as_int(error_analysis.get("uniqueUsers"), 0) or 0
    if unique_users <= 2 and count is not None and count >= 50:
        return True

    if draft_report:
        evidence = draft_report.get("evidence") or []
        conclusion = str(draft_report.get("conclusion") or "")
        if len(evidence) < 3 or len(conclusion) < 20:
            return True

    return False


def should_switch_playbook(
    *,
    skill_key: str,
    playbook_switched: bool = False,
    alarm_type: str | None = None,  # parsed 里的显式【类型】
    error_analysis: dict | None = None,
    monitor_detail: Any = None,  # 可选，用来拼更多文案
) -> str | None:
    """需要换本时返回新 skill key（如 "bff"）；否则 None。"""
    if playbook_switched:
        return None
    if (alarm_type or "").strip():
        return None
    if not error_analysis:
        return None

    blob = _build_detail_blob(error_analysis, monitor_detail)
    if not blob.strip():
        return None

    hint_key = _skill_key_from_meta(classify_by_name(blob))
    if hint_key == (skill_key or "").strip():
        return None
    if not _hint_trusted(hint_key, blob):
        return None
    return hint_key
