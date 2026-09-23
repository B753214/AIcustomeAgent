from __future__ import annotations

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.config import settings

# 进程内缓存：同一连接身份复用客户端（与 services.chat.get_llm 同思路）
_llm_cache: dict[tuple[Any, ...], BaseChatModel] = {}

# 角色 → 默认模型名（目前共用主模型；以后可改成独立 Settings 字段）
ROLE_MODELS: dict[str, str] = {
    "worker": settings.AIROBOT_LLM_MODEL,
    "router": settings.AIROBOT_LLM_MODEL,
    "judge": settings.AIROBOT_LLM_MODEL,
}

KNOWN_ROLES: tuple[str, ...] = tuple(ROLE_MODELS.keys())


def get_llm(**overrides: Any) -> BaseChatModel:
    """按参数创建（或复用）Chat 模型。

    识别字段：model / base_url / api_key / model_provider。
    其余 kwargs（如 temperature）原样传给 init_chat_model；
    若存在额外 kwargs，不走共享缓存，避免配置串扰。
    """
    base_url = overrides.pop("base_url", settings.AIROBOT_LLM_BASE_URL)
    api_key = overrides.pop("api_key", settings.AIROBOT_LLM_API_KEY)
    model = overrides.pop("model", settings.AIROBOT_LLM_MODEL)
    model_provider = overrides.pop("model_provider", settings.provider)
    extra = dict(overrides)

    kwargs: dict[str, Any] = {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "model_provider": model_provider,
        **extra,
    }

    if extra:
        return init_chat_model(**kwargs)

    key = (model, base_url, api_key, model_provider)
    if key not in _llm_cache:
        _llm_cache[key] = init_chat_model(
            base_url=base_url,
            api_key=api_key,
            model=model,
            model_provider=model_provider,
        )
    return _llm_cache[key]


class ModelGateway:
    """按角色获取 LLM；内部带缓存，供 Executor / Router 使用。"""

    def __init__(
        self,
        role_models: dict[str, str] | None = None,
    ) -> None:
        self._role_models = dict(role_models or ROLE_MODELS)
        self._roles = tuple(self._role_models.keys())
        self._usage: dict[str, Any] = {
            "calls": 0,
            "by_role": {r: 0 for r in self._roles},
        }

    @property
    def roles(self) -> tuple[str, ...]:
        return self._roles

    def resolve_model(self, role: str) -> str:
        """角色对应的默认模型名。"""
        if role not in self._role_models:
            raise ValueError(f"role {role!r} not in {list(self._roles)}")
        return self._role_models[role]

    def get(self, role: str, **overrides: Any) -> BaseChatModel:
        if role not in self._role_models:
            raise ValueError(f"role {role!r} not in {list(self._roles)}")

        params: dict[str, Any] = {
            "model": self._role_models[role],
            "base_url": settings.AIROBOT_LLM_BASE_URL,
            "api_key": settings.AIROBOT_LLM_API_KEY,
            "model_provider": settings.provider,
        }
        params.update(overrides)

        self._usage["calls"] += 1
        self._usage["by_role"][role] = self._usage["by_role"].get(role, 0) + 1
        return get_llm(**params)

    def record_usage(self, *, role: str | None = None, **fields: Any) -> None:
        """薄用量记账（H6 Budget 可再接）；先累计到实例字典。"""
        bucket = self._usage.setdefault("details", [])
        bucket.append({"role": role, **fields})

    def usage_snapshot(self) -> dict[str, Any]:
        return dict(self._usage)
