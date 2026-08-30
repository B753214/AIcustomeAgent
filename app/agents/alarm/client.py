async def fetch_monitor_context(url_or_text: str) -> str | None:
    """
    调 car_robot POST /api/analyze（SSE）。
    成功返回给 LLM 用的摘要字符串；失败返回 None（不抛给上层）。
    """