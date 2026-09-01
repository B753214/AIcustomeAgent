from langchain_mcp_adapters.client import MultiServerMCPClient
from app.config import settings

_amap_tools: list | None = None
async def get_amap_tools() ->list:
    global _amap_tools
    if _amap_tools is not None:
        return _amap_tools
    if not settings.amap_mcp_enabled or not settings.amap_maps_api_key:
        _amap_tools = []
        return _amap_tools
        # URL 带 key（Key 只从 settings 读，不要写死）
    try:
        url = f"{settings.amap_mcp_url}?key={settings.amap_maps_api_key}"

        client = MultiServerMCPClient({
            "amap": {
                "url": url,
                "transport": "streamable_http",
            }
        })
        _amap_tools = await client.get_tools()
    except Exception as e:
        print(f"[amap_mcp] 拉取工具失败: {e}")
        _amap_tools = []
    return _amap_tools


async def main():
    tools = await get_amap_tools()
    print(len(tools), [t.name for t in tools])
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())