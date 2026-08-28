from fastapi import Header, HTTPException
import secrets

from app.config import settings

async def verify_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    if not settings.api_key_enabled:
        return  # 开关关 → 直接放行
    if not settings.service_api_key:
        raise HTTPException(500, detail="已开启 API Key 但未配置 SERVICE_API_KEY")
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.service_api_key):
        raise HTTPException(401, detail="无效或缺失 API Key")

