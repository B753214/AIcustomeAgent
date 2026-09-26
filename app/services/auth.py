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


async def get_user_id(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> str:
    """解析调用方用户标识（无登录系统时由 Header / 网关注入）。

    - require_user_id=False：缺省或空 → \"anonymous\"
    - require_user_id=True：缺 Header → 401
    - 超长 → 400
    """
    uid = (x_user_id or "").strip()
    if uid:
        if len(uid) > settings.max_user_id_length:
            raise HTTPException(
                400,
                detail=f"X-User-Id 过长（最多 {settings.max_user_id_length} 字符）",
            )
        return uid
    if settings.require_user_id:
        raise HTTPException(401, detail="缺少 X-User-Id")
    return "anonymous"

