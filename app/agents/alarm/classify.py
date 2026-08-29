SKILL_MAP = {
    "ajx": {"type": "AJX报错", "skill": "wuying-ajx-error-troubleshooting"},
    "render": {"type": "渲染异常", "skill": "wuying-render-monitor-troubleshooting"},
    "bff": {"type": "BFF错误", "skill": "wuying-bff-error-troubleshooting"},
    "voc": {"type": "VOC", "skill": "wuying-voc-troubleshooting"},
    "precise": {"type": "精准报警", "skill": "wuying-precise-alarm-troubleshooting"},
}

def classify_by_name(name: str) -> dict:
    """根据指标名/告警名返回 SKILL_MAP 里某一项。"""
    s = name.lower()
    if any(kw in s for kw in ('ajx', 'ajax', 'jserror', 'js错误')):
        return SKILL_MAP["ajx"]
    if any(kw in s for kw in ('渲染', '白屏', '首屏', '展示缺失')):
        return SKILL_MAP["render"]
    if any(kw in s for kw in ('bff', '服务端')):
        return SKILL_MAP["bff"]
    if any(kw in s for kw in ('voc', '舆情', '用户反馈')):
        return SKILL_MAP["voc"]
    if '【精准】' in s:
        return SKILL_MAP["precise"]
    if any(kw in s for kw in ('code非1', '接口失败', '提交', '提单')):
        return SKILL_MAP["bff"]
    return SKILL_MAP["precise"]

def classify_alarm(parsed: dict) -> dict:
    """优先用 indicator，否则拼 business+hitRule；返回 {key, type, skill}。"""
    name = parsed.get("indicator", "").strip()
    if not name:
        name = f"{parsed.get('business', '')} {parsed.get('hitRule', '')}".strip()
    result = classify_by_name(name or "unknown")
    key = next((k for k,v in SKILL_MAP.items() if v is result), "precise")
    return {"key": key, **result}


if __name__ == "__main__":
    res1=classify_by_name("随便一个名字")  # 应返回 precise，不能 KeyError
    res2=classify_by_name("页面白屏")  # 应返回 render
    print(res1)
    print(res2)