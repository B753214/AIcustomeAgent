"""进程内语义缓存：双门限 + user scope + TTL/版本（M7-1/M7-2）。"""
from __future__ import annotations

import math
import time

from app.config import settings
from app.rag.lexical import tokenize


class SemanticCache:
    def __init__(
        self,
        cache_threshold: float = 0.75,
        lexical_threshold: float = 0.5,
        max_entries: int = 1000,
    ):
        self.cache_threshold = cache_threshold
        self.lexical_threshold = lexical_threshold
        self.max_entries = max_entries
        self._items: list[dict] = []
        self.hits = 0
        self.misses = 0
        self.cleared = 0

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(b * b for b in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    @staticmethod
    def _lexical_overlap(a: str, b: str) -> float:
        ta = set(tokenize(a))
        tb = set(tokenize(b))
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / min(len(ta), len(tb))

    @staticmethod
    def _scope(user_id: str | None, session_id: str | None = None) -> str:
        uid = (user_id or "").strip() or "anonymous"
        return uid

    def get(
        self,
        query_vec: list[float],
        query_text: str = "",
        user_id: str | None = None,
    ) -> dict | None:
        want = self._scope(user_id)
        best_item = None
        best_sim = -1.0
        now = time.time()
        ttl = settings.cache_ttl_seconds
        version = settings.cache_version

        for item in self._items:
            if item.get("scope") != want:
                continue
            if item.get("version") != version:
                continue
            if ttl > 0 and now - item["ts"] > ttl:
                continue
            sim = self._cosine(query_vec, item["vec"])
            if sim < self.cache_threshold:
                continue
            if (
                query_text
                and item.get("query")
                and self._lexical_overlap(query_text, item["query"]) < self.lexical_threshold
            ):
                continue
            if sim > best_sim:
                best_sim = sim
                best_item = item

        if best_item is not None:
            self.hits += 1
            return dict(best_item["result"])
        self.misses += 1
        return None

    def put(
        self,
        query_vec: list[float],
        query_text: str = "",
        result: dict | None = None,
        user_id: str | None = None,
    ):
        self._items.append({
            "scope": self._scope(user_id),
            "vec": query_vec,
            "result": dict(result or {}),
            "ts": time.time(),
            "query": query_text,
            "version": settings.cache_version,
        })
        if len(self._items) > self.max_entries:
            self._items = sorted(self._items, key=lambda x: x["ts"])[len(self._items) // 2 :]

    def clear(self) -> None:
        self.cleared += len(self._items)
        self._items = []

    def stats(self) -> dict:
        return {
            "enabled": True,
            "threshold": self.cache_threshold,
            "lexical_threshold": self.lexical_threshold,
            "size": len(self._items),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / (self.hits + self.misses), 4)
            if (self.hits + self.misses)
            else 0.0,
            "version": settings.cache_version,
            "ttl_seconds": settings.cache_ttl_seconds,
        }


semantic_cache = SemanticCache(
    settings.cache_threshold,
    settings.cache_lexical_threshold,
    settings.max_entries_cache,
)
