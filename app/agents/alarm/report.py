"""报告组装：规则证据 + URL 报告（对齐 analyzeErrorDetails / buildUrlReport）。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.agents.alarm.classify import classify_by_name


def should_skip_analysis(rate_data: dict | None) -> str | None:
    """count==0 时返回 skip 理由；否则 None。"""
    if not rate_data:
        return None
    count = rate_data.get("count")
    if count is None:
        return None
    try:
        n = int(count)
    except (TypeError, ValueError):
        return None
    if n == 0:
        name = rate_data.get("name") or rate_data.get("remark") or "该监控"
        return f"{name} 当前无失败"
    return None


def analyze_error_details(detail_data: Any) -> dict | None:
    raw_list = (
        detail_data
        if isinstance(detail_data, list)
        else (detail_data.get("list") if isinstance(detail_data, dict) else None)
    )
    if not isinstance(raw_list, list) or not raw_list:
        return None
    detail_list = [x for x in raw_list[:50] if isinstance(x, dict)]
    if not detail_list:
        return None

    err_msg_count: dict[str, int] = {}
    uid_set: set[str] = set()
    err_flag_count: dict[str, int] = {}
    for item in detail_list:
        msg = item.get("err_msg") or "未知错误"
        err_msg_count[msg] = err_msg_count.get(msg, 0) + 1
        if item.get("uid"):
            uid_set.add(str(item["uid"]))
        flag = item.get("err_flag") or ""
        if flag:
            err_flag_count[flag] = err_flag_count.get(flag, 0) + 1

    sorted_msgs = sorted(err_msg_count.items(), key=lambda x: x[1], reverse=True)
    top_errors = [f"{msg}（{count}次）" for msg, count in sorted_msgs[:5]]
    top_errors_raw = [{"msg": msg, "count": count} for msg, count in sorted_msgs[:5]]
    is_single_user = len(uid_set) == 1
    top_err_flag = (
        sorted(err_flag_count.items(), key=lambda x: x[1], reverse=True)[0][0]
        if err_flag_count
        else ""
    )

    return {
        "topErrors": top_errors,
        "topErrorsRaw": top_errors_raw,
        "uniqueUsers": len(uid_set),
        "isSingleUser": is_single_user,
        "singleUid": next(iter(uid_set)) if is_single_user else None,
        "total": len(detail_list),
        "errUrl": detail_list[0].get("url") or "",
        "errFlag": top_err_flag,
        "pageName": detail_list[0].get("page_name") or "",
        "scene": detail_list[0].get("scene") or "",
    }


def parse_ai_result(ai_text: str) -> dict:
    sections: dict[str, Any] = {
        "conclusion": "",
        "evidence": [],
        "shortTerm": "",
        "longTerm": "",
    }
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", ai_text or "").strip()

    m = re.search(r"排查结论\s*\n([\s\S]*?)(?=\n证据链|$)", cleaned)
    if m:
        sections["conclusion"] = m.group(1).strip()

    m = re.search(r"证据链\s*\n([\s\S]*?)(?=\n修复建议|$)", cleaned)
    if m:
        sections["evidence"] = [
            re.sub(r"^\d+\.\s*", "", line).strip()
            for line in m.group(1).strip().split("\n")
            if line.strip()
        ]

    m = re.search(r"短期[：:]\s*([\s\S]*?)(?=\n长期|$)", cleaned)
    if m:
        sections["shortTerm"] = m.group(1).strip()

    m = re.search(r"长期[：:]\s*([\s\S]*?)$", cleaned)
    if m:
        sections["longTerm"] = m.group(1).strip()

    return sections


def _guess_root_cause(name: str) -> str:
    s = (name or "").lower()
    if "填单提交" in s or "提单" in s:
        return "下单提交链路异常，可能为后端交易服务处理失败、库存/价格校验不通过或下游支付渠道异常"
    if "渲染" in s:
        return "页面渲染链路异常，可能为数据源接口返回异常或前端组件渲染错误"
    if "取消订单" in s:
        return "取消订单链路异常，可能为订单状态不允许取消或退款服务响应异常"
    if "退款" in s:
        return "退款链路异常，可能为退款条件不满足或下游支付渠道异常"
    if "ajx" in s or "ajax" in s:
        return "前端AJAX请求异常，可能为接口超时、返回格式异常或网络波动"
    return "需结合日志明细进一步定位具体失败原因"


def _generate_suggestion(skill_type: str, error_analysis: dict | None) -> dict[str, str]:
    if error_analysis and error_analysis.get("topErrors"):
        main_err = error_analysis["topErrors"][0]
        short = f"排查主要错误「{main_err}」的触发原因"
        if error_analysis.get("errUrl"):
            short += f"，检查 {error_analysis['errUrl']} 接口的稳定性，增加重试机制或降级策略"
        return {
            "shortTerm": short,
            "longTerm": "深入分析接口返回错误的具体原因，修复服务端逻辑问题",
        }
    mapping = {
        "AJX报错": (
            "检查前端AJAX请求日志定位错误码和堆栈，确认后端接口响应状态和耗时",
            "排查网络链路，优化接口超时和重试策略",
        ),
        "渲染异常": (
            "检查渲染接口返回数据完整性，排查前端JS异常日志",
            "确认是否有近期发布兼容性问题，优化渲染容错逻辑",
        ),
        "BFF错误": (
            "查看BFF服务日志定位失败原因和错误码，检查下游服务调用链路",
            "确认接口入参合法性，优化服务端异常处理",
        ),
        "VOC": (
            "查看VOC工单详情复现用户问题，收集设备/网络环境信息",
            "定位问题模块推进修复",
        ),
        "精准报警": (
            "查看日志明细确认具体失败原因，检查相关服务链路",
            "确认是否需要紧急介入修复，完善监控覆盖",
        ),
    }
    short, long = mapping.get(skill_type, mapping["精准报警"])
    return {"shortTerm": short, "longTerm": long}


def build_url_report(
    rate_data: dict,
    error_analysis: dict | None,
    monitor_url: str | None,
    ai_result: str | None,
    *,
    channel: str = "",
    skill: dict | None = None,
) -> str:
    """对齐 JS buildUrlReport（纯文本章节，非 markdown 符号）。"""
    name = rate_data.get("name") or rate_data.get("remark") or "未知监控"
    cls = skill or classify_by_name(name)
    count = rate_data.get("count")
    try:
        count_n = int(count) if count is not None else 0
    except (TypeError, ValueError):
        count_n = 0

    now = datetime.now()
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")

    if ai_result:
        ai = parse_ai_result(ai_result)
        conclusion = ai["conclusion"] or f"{name}存在异常，当前失败{count_n}次。"
        evidence = ai["evidence"] or ["AI分析未返回具体证据。"]
        short_term = ai["shortTerm"] or "检查相关服务链路"
        long_term = ai["longTerm"] or "完善监控覆盖"
    else:
        name_clean = re.sub(r"^【精准】", "", name)
        if error_analysis and error_analysis.get("topErrorsRaw"):
            main_err = error_analysis["topErrorsRaw"][0]["msg"]
            conclusion = f"{name_clean}存在异常，主要表现为返回异常错误码{main_err}。"
        else:
            conclusion = f"{name_clean}存在异常，当前失败{count_n}次。" + _guess_root_cause(
                name
            )
        evidence = []
        if error_analysis and error_analysis.get("topErrorsRaw"):
            evidence.append(
                f"报警明细显示多次出现\"返回异常 {error_analysis['topErrorsRaw'][0]['msg']}\"错误信息。"
            )
            if error_analysis.get("errUrl"):
                evidence.append(
                    f"错误发生在{error_analysis['errUrl']}接口调用过程中。"
                )
        else:
            evidence.append(
                f"当前时间段内失败{count_n}次，"
                f"昨日{rate_data.get('yesterdayCount', '-')}次，"
                f"上周{rate_data.get('lastWeekCount', '-')}次。"
            )
        sug = _generate_suggestion(cls.get("type") or "精准报警", error_analysis)
        short_term = sug["shortTerm"]
        long_term = sug["longTerm"]

    lines = [
        "排查报告",
        "基本信息",
        f"• 报警类型：{cls.get('type') or '未知'}",
    ]
    if monitor_url:
        lines.append(f"• 报警链接：{monitor_url}")
    if cls.get("skill"):
        lines.append(f"• 调用 Skill：{cls['skill']}")
    if channel:
        lines.append(f"• 拉数通道：{channel}")
    lines.append(f"• 排查时间：{time_str}")
    lines.append("排查结论")
    lines.append(conclusion)
    lines.append("证据链")
    for i, e in enumerate(evidence, 1):
        lines.append(f"{i}. {e}")
    lines.append("修复建议")
    lines.append(f"• 短期：{short_term}")
    lines.append(f"• 长期：{long_term}")
    lines.append("下一步行动")
    lines.append("• [ ] 联系相关服务方确认接口异常原因")
    return "\n".join(lines)


def build_skip_report(reason: str, *, monitor_url: str = "", channel: str = "") -> str:
    lines = [
        "排查报告",
        "基本信息",
    ]
    if monitor_url:
        lines.append(f"• 报警链接：{monitor_url}")
    if channel:
        lines.append(f"• 拉数通道：{channel}")
    lines.append("排查结论")
    lines.append(reason + "，无需深入分析。")
    lines.append("证据链")
    lines.append("1. 当前失败次数为 0")
    lines.append("修复建议")
    lines.append("• 短期：确认监控阈值与数据上报是否正常")
    lines.append("• 长期：避免过敏阈值导致误报")
    return "\n".join(lines)
