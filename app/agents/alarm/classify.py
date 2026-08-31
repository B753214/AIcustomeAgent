"""告警类型 → playbook/skill。有显式分类则直接用，否则按指标名关键词推断。"""
from __future__ import annotations

SKILL_MAP = {
    "ajx": {"type": "AJX报错", "skill": "wuying-ajx-error-troubleshooting"},
    "render": {"type": "渲染异常", "skill": "wuying-render-monitor-troubleshooting"},
    "bff": {"type": "BFF错误", "skill": "wuying-bff-error-troubleshooting"},
    "voc": {"type": "VOC", "skill": "wuying-voc-troubleshooting"},
    "precise": {"type": "精准报警", "skill": "wuying-precise-alarm-troubleshooting"},
}

# 显式文案 / 别名 → skill key
_EXPLICIT_ALIASES: dict[str, str] = {
    "ajx": "ajx",
    "ajax": "ajx",
    "jserror": "ajx",
    "js错误": "ajx",
    "ajx报错": "ajx",
    "render": "render",
    "渲染": "render",
    "渲染异常": "render",
    "白屏": "render",
    "bff": "bff",
    "bff错误": "bff",
    "服务端": "bff",
    "voc": "voc",
    "舆情": "voc",
    "precise": "precise",
    "精准": "precise",
    "精准报警": "precise",
    "generic": "precise",
}


def _resolve_explicit(raw: str) -> dict | None:
    """用户已给出分类时解析为 {key, type, skill}；无法识别返回 None。"""
    s = (raw or "").strip()
    if not s:
        return None
    lower = s.lower()
    # 直接是 key
    if lower in SKILL_MAP:
        return {"key": lower, **SKILL_MAP[lower]}
    # 完整 type 名
    for key, meta in SKILL_MAP.items():
        if s == meta["type"] or lower == meta["type"].lower():
            return {"key": key, **meta}
        if s == meta["skill"] or lower == meta["skill"].lower():
            return {"key": key, **meta}
    # 别名（整词或包含）
    if lower in _EXPLICIT_ALIASES:
        key = _EXPLICIT_ALIASES[lower]
        return {"key": key, **SKILL_MAP[key]}
    for alias, key in _EXPLICIT_ALIASES.items():
        if alias in lower or alias in s:
            return {"key": key, **SKILL_MAP[key]}
    return None


def classify_by_name(name: str) -> dict:
    """根据指标名/告警名返回 SKILL_MAP 里某一项。"""
    s = name.lower()
    if any(kw in s for kw in ("ajx", "ajax", "jserror", "js错误")):
        return SKILL_MAP["ajx"]
    if any(kw in s for kw in ("渲染", "白屏", "首屏", "展示缺失")):
        return SKILL_MAP["render"]
    if any(kw in s for kw in ("bff", "服务端")):
        return SKILL_MAP["bff"]
    if any(kw in s for kw in ("voc", "舆情", "用户反馈")):
        return SKILL_MAP["voc"]
    if "【精准】" in s:
        return SKILL_MAP["precise"]
    if any(kw in s for kw in ("code非1", "接口失败", "提交", "提单")):
        return SKILL_MAP["bff"]
    return SKILL_MAP["precise"]


def classify_alarm(parsed: dict) -> dict:
    """优先用显式分类（【类型】/【报警类型】等）；否则按 indicator 推断。

    返回 {key, type, skill}。
    """
    explicit = _resolve_explicit(str(parsed.get("alarmType") or ""))
    if explicit:
        return explicit

    name = (parsed.get("indicator") or "").strip()
    if not name:
        name = f"{parsed.get('business', '')} {parsed.get('hitRule', '')}".strip()
    result = classify_by_name(name or "unknown")
    key = next((k for k, v in SKILL_MAP.items() if v is result), "precise")
    return {"key": key, **result}


if __name__ == "__main__":
    print(classify_by_name("随便一个名字"))
    print(classify_by_name("页面白屏"))
    print(classify_alarm({"alarmType": "BFF", "indicator": "页面白屏"}))  # 应 bff，不跟白屏
