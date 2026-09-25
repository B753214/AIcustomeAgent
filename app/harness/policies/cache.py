from __future__ import annotations

from typing import Any


class CachePolicy:
    """H6-1 最小可用：默认 no-op 缓存。

    key 约定由调用方自行包含 agent/prompt/模型版本，且勿塞入敏感原文。
    """

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None
