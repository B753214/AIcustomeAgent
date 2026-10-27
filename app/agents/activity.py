"""运营活动查询（Day1 Mock；Day7 可换成真实 API）。"""
from __future__ import annotations

from typing import Any

# 关键词命中任一条 tags 即入选；空关键词返回全部（「最近有什么活动」）
MOCK_ACTIVITIES: list[dict[str, Any]] = [
    {
        "id": "newbie",
        "title": "新人专享满减",
        "time": "长期有效",
        "rule": "新注册用户首单满 50 减 20",
        "entry": "我的-优惠券-新人礼包",
        "tags": ("新人", "新用户", "满减", "优惠券", "优惠"),
    },
    {
        "id": "weekend",
        "title": "周末免运费",
        "time": "每周五 00:00 至周日 23:59",
        "rule": "订单满 99 元包邮，不与运费券叠加",
        "entry": "结算页自动抵扣",
        "tags": ("周末", "包邮", "运费", "周五", "周六", "周日"),
    },
    {
        "id": "double11",
        "title": "双十一预热满减",
        "time": "11 月 1 日–11 月 11 日",
        "rule": "全场满 200 减 30，满 400 减 80",
        "entry": "活动会场-双十一专区",
        "tags": ("双十一", "双11", "预热", "满减", "会场"),
    },
    {
        "id": "old_for_new",
        "title": "以旧换新补贴",
        "time": "本季度内",
        "rule": "指定品类回收估价额外补贴 10%",
        "entry": "卖货-以旧换新",
        "tags": ("以旧换新", "回收", "补贴", "卖货"),
    },
    {
        "id": "member",
        "title": "会员日额外积分",
        "time": "每月 8 日",
        "rule": "会员购物积分 x2，封顶 5000",
        "entry": "会员中心-积分商城",
        "tags": ("会员", "积分", "会员日"),
    },
]

_NO_MATCH = "暂无相关活动。可以问问「最近有什么活动」或「新人优惠」。"


def _format_item(item: dict[str, Any]) -> str:
    return (
        f"【{item['title']}】\n"
        f"时间：{item['time']}\n"
        f"规则：{item['rule']}\n"
        f"入口：{item['entry']}"
    )


def match_activities(keyword: str) -> list[dict[str, Any]]:
    q = (keyword or "").strip().lower()
    if not q or q in ("活动", "优惠", "最近", "有什么活动", "最近有什么活动"):
        return list(MOCK_ACTIVITIES)
    hits: list[dict[str, Any]] = []
    for item in MOCK_ACTIVITIES:
        blob = " ".join(
            [item["title"], item["rule"], item["entry"], *item["tags"]]
        ).lower()
        if q in blob or any(tag.lower() in q or q in tag.lower() for tag in item["tags"]):
            hits.append(item)
    return hits


def query_activity(keyword: str) -> str:
    """按关键词查询平台运营活动（当前为 Mock）。

    Args:
        keyword: 用户话术或关键词，如「周末」「新人」「满减」；空则返回近期全部活动。
    """
    hits = match_activities(keyword)
    if not hits:
        return _NO_MATCH
    header = f"为你找到 {len(hits)} 个活动：\n\n"
    return header + "\n\n".join(_format_item(x) for x in hits)
