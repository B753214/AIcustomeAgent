"""告警输入启发式检测（对齐 car_robot detectInputType，不调 LLM）。"""
from __future__ import annotations

import re


def detect_input_type(content: str) -> str:
    """返回 'alarm' | 'url' | 'unknown'。"""
    text = content or ""
    if re.search(r"【指标】|【当前指标】|【配置ID】|命中规则|P[0-3]\s", text):
        return "alarm"
    if "info-plate.fc.alibaba-inc.com" in text or "marketConfigId=" in text:
        return "url"
    return "unknown"


def is_alarm_message(content: str) -> bool:
    """结构化告警或监控 URL，均视为应走告警 Agent。"""
    return detect_input_type(content) in ("alarm", "url")


if __name__ == "__main__":
    samples = [
        "P1 【指标】：填单BFF\n【配置ID】：11664",
        "七天无理由退货怎么申请？",
        "https://info-plate.fc.alibaba-inc.com/monitor/searchall?marketConfigId=11664",
    ]
    for s in samples:
        print(detect_input_type(s), is_alarm_message(s), "|", s[:40].replace("\n", " "))
