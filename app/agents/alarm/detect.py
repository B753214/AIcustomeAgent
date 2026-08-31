"""告警输入启发式检测（不调 LLM）。

detect_input_type：细分类（alarm 字段 / url / unknown），对齐 car_robot 对照。
is_alarm_message：强短路条件——须同时具备告警字段与监控链接。
"""
from __future__ import annotations

import re

_FIELD_RE = re.compile(r"【指标】|【当前指标】|【配置ID】|命中规则|P[0-3]\s")
_URL_RE = re.compile(r"info-plate\.fc\.alibaba-inc\.com|marketConfigId=")


def _has_alarm_fields(text: str) -> bool:
    return bool(_FIELD_RE.search(text or ""))


def _has_monitor_url(text: str) -> bool:
    return bool(_URL_RE.search(text or ""))


def detect_input_type(content: str) -> str:
    """返回 'alarm' | 'url' | 'unknown'（单侧命中也分别标出，便于调试）。"""
    text = content or ""
    fields = _has_alarm_fields(text)
    url = _has_monitor_url(text)
    if fields and url:
        return "alarm"
    if fields:
        return "alarm"
    if url:
        return "url"
    return "unknown"


def is_alarm_message(content: str) -> bool:
    """仅当「告警字段 + 监控链接」同时存在时，才启发式直达告警 Agent。"""
    text = content or ""
    return _has_alarm_fields(text) and _has_monitor_url(text)


if __name__ == "__main__":
    samples = [
        "P1 【指标】：填单BFF\n【配置ID】：11664\nhttps://info-plate.fc.alibaba-inc.com/monitor/searchall?marketConfigId=11664",
        "P1 【指标】：填单BFF\n【配置ID】：11664",
        "https://info-plate.fc.alibaba-inc.com/monitor/searchall?marketConfigId=11664",
        "七天无理由退货怎么申请？",
        "什么是 P1 告警？",
    ]
    for s in samples:
        print(
            detect_input_type(s),
            is_alarm_message(s),
            "|",
            s[:50].replace("\n", " "),
        )
