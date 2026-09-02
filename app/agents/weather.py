import requests

from app.config import settings

_TOOL_ERROR_PREFIX = "[TOOL_ERROR]"


def query_weather(location: str) -> str:
    """获取指定位置的实时天气。

    Args:
        location: 所查询的位置，可使用城市拼音（如「beijing」）、
                  和风天气 v3 ID、经纬度（如「116.4074,39.9042」）等。
    """
    API = "https://api.seniverse.com/v3/weather/now.json"
    try:
        resp = requests.get(
            API,
            params={
                "key": '',
                "location": location,
                "language": "zh-Hans",
                "unit": "c",
            },
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return f"{_TOOL_ERROR_PREFIX} 天气查询异常：{type(e).__name__}: {e}"

    results = data.get("results") or []
    if not results:
        return f"{_TOOL_ERROR_PREFIX} 天气接口未返回结果，原始响应：{data}"

    first = results[0]
    now = first.get("now") or {}
    loc = first.get("location") or {}
    last_update = first.get("last_update") or ""

    name = loc.get("name") or location
    text = now.get("text") or "-"
    temp = now.get("temperature") or "-"

    return (
        f"{name}实时天气：\n"
        f"天气：{text}\n"
        f"气温：{temp}℃\n"
        f"发布时间：{last_update}"
    )


if __name__ == "__main__":
    print(query_weather("beijing"))
    print("---")
    print(query_weather("杭州"))