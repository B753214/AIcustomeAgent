import re


def parse_alarm_message(text: str) -> dict:
    """解析钉钉/监控告警正文，缺字段用 '' 或 0。"""
    def get(key: str) -> str:
        m = re.search(rf"【{re.escape(key)}】[：:]\s*(.+?)(?:\n|$)", text)
        return m.group(1).strip() if m else ""

    level_match = re.search(r"^(P\d)\s", text, re.MULTILINE)
    current_match = re.search(r"【当前指标】[：:]\s*([\d,.]+)", text)
    yesterday_match = re.search(
        r"【昨日指标】[：:]\s*([\d,.]+)\s+日环比[：:]?\s*([↑↓]?[\d.]+%)", text
    )
    last_week_match = re.search(
        r"【上周指标】[：:]\s*([\d,.]+)\s+周同比[：:]?\s*([↑↓]?[\d.]+%)", text
    )
    rule_detail_match = re.search(r"规则\d+[：:]\s*(.+?)(?:\n|$)", text)
    detail_url_match = re.search(
        r"https?://info-plate\.fc\.alibaba-inc\.com/[^\s)]+", text
    )

    return {
        "level": level_match.group(1) if level_match else "",
        "indicator": get("指标"),
        "business": get("业务"),
        "configId": get("配置ID"),
        "cp": get("CP"),
        "current": int(current_match.group(1).replace(",", "")) if current_match else 0,
        "yesterdayValue": int(yesterday_match.group(1).replace(",", "")) if yesterday_match else 0,
        "chainRatio": yesterday_match.group(2) if yesterday_match else "",
        "lastWeekValue": int(last_week_match.group(1).replace(",", "")) if last_week_match else 0,
        "yearRatio": last_week_match.group(2) if last_week_match else "",
        "hitRule": get("命中规则"),
        "ruleDetail": rule_detail_match.group(1).strip() if rule_detail_match else "",
        "timeRange": get("数据范围"),
        "execTime": get("执行时间"),
        "owners": get("负责人"),
        "detailUrl": detail_url_match.group(0) if detail_url_match else "",
    }


def extract_monitor_url(text: str) -> str | None:
    m = re.search(r'https?://info-plate\.fc\.alibaba-inc\.com/[^\s)]+', text)
    return m.group(0) if m else None