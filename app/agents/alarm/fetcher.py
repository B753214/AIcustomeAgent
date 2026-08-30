"""经 MCP 拉取监控配置 / 明细；失败返回 None（正文降级）。"""
from __future__ import annotations

import json
from typing import Any

from app.agents.alarm.mcp import McpClient
from app.config import settings


def _tool_text(result: dict) -> str | None:
    content = result.get("content") or []
    if not content:
        return None
    first = content[0]
    if isinstance(first, dict):
        return first.get("text")
    return None


def _unwrap_market_config(parsed: Any) -> dict:
    """兼容 datas 包裹或直接对象。"""
    if not isinstance(parsed, dict):
        return {}
    datas = parsed.get("datas")
    if datas is not None:
        if isinstance(datas, list):
            return datas[0] if datas and isinstance(datas[0], dict) else {}
        if isinstance(datas, dict):
            return datas
    # 有的接口再包一层 data
    data = parsed.get("data")
    if isinstance(data, dict):
        return _unwrap_market_config(data) or data
    return parsed


def _detail_list(detail_data: Any) -> list:
    if detail_data is None:
        return []
    if isinstance(detail_data, list):
        return detail_data
    if isinstance(detail_data, dict):
        lst = detail_data.get("list")
        if isinstance(lst, list):
            return lst
    return []


def _build_monitor_rate(market_config: dict, detail_data: Any) -> dict:
    """补齐 Node 版 MCP 缺少的 monitorRate。"""
    name = (
        market_config.get("name")
        or market_config.get("remark")
        or market_config.get("indicator")
        or "未知监控"
    )
    items = _detail_list(detail_data)
    count: int | None
    if items:
        count = len(items)
    else:
        raw = market_config.get("count")
        count = int(raw) if raw is not None and str(raw).isdigit() else None

    rate: dict[str, Any] = {"name": name, "count": count}
    for src, dst in (
        ("yesterdayCount", "yesterdayCount"),
        ("yesterday_count", "yesterdayCount"),
        ("lastWeekCount", "lastWeekCount"),
        ("last_week_count", "lastWeekCount"),
    ):
        if market_config.get(src) is not None:
            rate[dst] = market_config[src]
    return rate


async def fetch_monitor_data(
    *,
    market_config_id: str,
    biz_type: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict | None:
    """成功返回含 monitorRate/monitorDetail/channel；失败返回 None。"""
    if not settings.alarm_mcp_enabled or not settings.alarm_mcp_token:
        return None

    try:
        client = McpClient()
        cfg_res = await client.call_tool(
            "query_business_market_config",
            {"params": {"id": market_config_id}},
        )
        raw = _tool_text(cfg_res)
        if not raw:
            print("[MCP] query_business_market_config 无 content.text")
            return None
        market_config = _unwrap_market_config(json.loads(raw))
        if not market_config:
            print("[MCP] marketConfig 为空")
            return None

        detail_data: Any = None
        try:
            det_res = await client.call_tool(
                "ability_monitor_detail",
                {
                    "params": {
                        "marketConfigId": market_config_id,
                        "bizType": biz_type or "30",
                        "startTime": start_time,
                        "endTime": end_time,
                    }
                },
            )
            det_raw = _tool_text(det_res)
            if det_raw:
                detail_data = json.loads(det_raw)
        except Exception as err:
            print(f"[MCP] detail failed: {err}")

        monitor_rate = _build_monitor_rate(market_config, detail_data)
        return {
            "channel": "mcp",
            "marketConfig": market_config,
            "monitorRate": monitor_rate,
            "monitorDetail": detail_data,
        }
    except Exception as err:
        print(f"[MCP] fetch failed: {err}")
        return None
