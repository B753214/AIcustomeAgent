"""明细格式化（对齐 fc_monitor.js formatDetailForLLM）。"""
from __future__ import annotations

from typing import Any

_DETAIL_MAX_CHARS = 3000


def format_detail_for_llm(detail_data: Any, max_chars: int = _DETAIL_MAX_CHARS) -> str:
    if detail_data is None:
        return "无明细数据"
    if isinstance(detail_data, list):
        items = detail_data
    elif isinstance(detail_data, dict):
        items = detail_data.get("list") or []
        if not isinstance(items, list):
            items = []
    else:
        return "无明细数据"
    if not items:
        return "无明细数据"

    # 优先展示不同错误/用户的代表样本，避免首批重复错误挤掉新页证据。
    representatives = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("err_msg", "")), str(item.get("uid", "")), str(item.get("url", "")))
        if key not in seen:
            seen.add(key)
            representatives.append(item)
    rows: list[str] = []
    for i, item in enumerate(representatives[:50]):
        if not isinstance(item, dict):
            continue
        parts: list[str] = []
        if item.get("time"):
            parts.append(f"时间:{item['time']}")
        if item.get("err_msg"):
            parts.append(f"错误:{item['err_msg']}")
        if item.get("err_flag"):
            parts.append(f"标志:{item['err_flag']}")
        if item.get("url"):
            parts.append(f"接口:{item['url']}")
        if item.get("page_name"):
            parts.append(f"页面:{item['page_name']}")
        if item.get("scene"):
            parts.append(f"场景:{item['scene']}")
        if item.get("uid"):
            parts.append(f"uid:{item['uid']}")
        rows.append(f"{i + 1}. {' | '.join(parts)}")
    text = "\n".join(rows) if rows else "无明细数据"
    if len(text) > max_chars:
        return text[:max_chars] + "\n…(已截断)"
    return text
