"""P5-3 语义缓存单元测试。"""
import math

import pytest

from app.services.semantic_cache import SemanticCache


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def test_cosine_helper_baseline():
    assert _cosine([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)
    assert _cosine([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]) == pytest.approx(0.0)
    assert _cosine([1.0, 0.0, 0.0], [0.8, 0.6, 0.0]) == pytest.approx(0.8, rel=1e-3)


def test_double_gate_hit():
    """向量够像 + 词面够像 → 命中。"""
    cache = SemanticCache(cache_threshold=0.75, lexical_threshold=0.5)
    vec_a = [1.0, 0.0, 0.0]
    vec_b = [0.8, 0.6, 0.0]  # 与 vec_a 余弦 ≈ 0.8
    result = {"reply": "运费由卖家承担", "intent": "knowledge", "sources": ["kb#1"]}
    cache.put(vec_a, "七天无理由退货怎么申请", result)

    hit = cache.get(vec_b, "无理由退货如何申请")
    assert hit is not None
    assert hit["reply"] == "运费由卖家承担"
    assert hit["intent"] == "knowledge"
    assert cache.stats()["hits"] == 1


def test_vector_similar_but_lexical_miss():
    """向量相似但词面完全不同 → 不命中（防误命中）。"""
    cache = SemanticCache(cache_threshold=0.75, lexical_threshold=0.5)
    vec_b = [0.8, 0.6, 0.0]
    cache.put([1.0, 0.0, 0.0], "七天无理由退货怎么申请", {"reply": "r", "intent": "knowledge"})

    assert cache.get(vec_b, "今天天气怎么样") is None
    assert cache.stats()["misses"] == 1


def test_lexical_similar_but_vector_miss():
    """词面相近但向量不相似 → 不命中。"""
    cache = SemanticCache(cache_threshold=0.75, lexical_threshold=0.5)
    cache.put([1.0, 0.0, 0.0], "七天无理由退货怎么申请", {"reply": "r", "intent": "knowledge"})

    assert cache.get([0.0, 1.0, 0.0], "七天无理由退货怎么申请") is None


def test_pick_best_candidate_when_top_cosine_fails_lexical():
    """余弦最高的候选词面不合格时，应命中次优但双门限均通过的条目。"""
    cache = SemanticCache(cache_threshold=0.75, lexical_threshold=0.5)
    cache.put(
        [1.0, 0.0, 0.0],
        "退货的运费谁承担",
        {"reply": "运费答案", "intent": "knowledge"},
    )
    cache.put(
        [0.75, 0.661, 0.0],
        "七天无理由退货怎么申请",
        {"reply": "退货答案", "intent": "knowledge"},
    )

    hit = cache.get([0.985, 0.174, 0.0], "无理由退货如何申请")
    assert hit is not None
    assert hit["reply"] == "退货答案"


def test_stats_hit_rate():
    cache = SemanticCache()
    cache.get([1.0, 0.0], "a")
    cache.put([1.0, 0.0], "a", {"reply": "r", "intent": "chat"})
    cache.get([1.0, 0.0], "a")

    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["size"] == 1
    assert stats["hit_rate"] == 0.5


def test_clear():
    cache = SemanticCache()
    cache.put([1.0, 0.0], "q", {"reply": "r", "intent": "chat"})
    cache.clear()
    assert cache.stats()["size"] == 0
    assert cache.cleared == 1


def test_get_returns_result_dict_not_internal_item():
    """get 应返回 result 对话 dict，而不是内部 {vec, query, ts} 结构。"""
    cache = SemanticCache(cache_threshold=0.5, lexical_threshold=0.1)
    payload = {"reply": "你好", "intent": "chat", "sources": [], "engine": "langchain"}
    cache.put([1.0, 0.0], "你好", payload)

    hit = cache.get([1.0, 0.0], "你好")
    assert hit == payload
    assert "vec" not in hit
    assert "ts" not in hit
