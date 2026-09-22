from types import SimpleNamespace

import pytest

from app.rag import milvus_store
from app.rag import retriever as retriever_module
from app.rag.reranker import Reranker
from app.rag.retriever import KnowledgeBase
from app.services.chunk_service import get_chunks_by_ids


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _statement):
        return _ScalarResult(self._rows)


@pytest.mark.asyncio
async def test_get_chunks_by_ids_preserves_requested_order():
    rows = [
        SimpleNamespace(id="chunk-c"),
        SimpleNamespace(id="chunk-a"),
        SimpleNamespace(id="chunk-b"),
    ]

    result = await get_chunks_by_ids(
        ["chunk-a", "chunk-b", "chunk-c"], _FakeSession(rows)
    )

    assert [chunk.id for chunk in result] == ["chunk-a", "chunk-b", "chunk-c"]


def test_search_vectors_uses_milvus_limit(monkeypatch):
    calls = []

    class FakeClient:
        def search(self, **kwargs):
            calls.append(kwargs)
            return [[]]

    monkeypatch.setattr(milvus_store, "get_milvus_client", lambda: FakeClient())

    assert milvus_store.search_vectors([0.1, 0.2], top_k=10) == []
    assert calls[0]["limit"] == 10
    assert "top_k" not in calls[0]


@pytest.mark.asyncio
async def test_search_vector_passes_top_k_and_keeps_hit_order(monkeypatch):
    captured = {}

    def fake_search_vectors(_query_vector, top_k):
        captured["top_k"] = top_k
        return [{"chunk_id": "chunk-a"}, {"chunk_id": "chunk-b"}]

    async def fake_get_chunks_by_ids(chunk_ids, _store):
        captured["chunk_ids"] = chunk_ids
        return [SimpleNamespace(id=chunk_id) for chunk_id in chunk_ids]

    monkeypatch.setattr(retriever_module, "search_vectors", fake_search_vectors)
    monkeypatch.setattr(retriever_module, "get_chunks_by_ids", fake_get_chunks_by_ids)

    kb = object.__new__(KnowledgeBase)
    kb._store = object()
    kb.embed_query = lambda _query: [0.1, 0.2]

    result = await kb.search_vector("query", top_k=10)

    assert captured == {"top_k": 10, "chunk_ids": ["chunk-a", "chunk-b"]}
    assert [chunk.id for chunk in result] == ["chunk-a", "chunk-b"]


@pytest.mark.asyncio
async def test_search_hybrid_uses_requested_candidate_and_fusion_limits(monkeypatch):
    captured = {}
    vector_docs = [SimpleNamespace(id=f"v-{index}") for index in range(5)]
    bm25_docs = [SimpleNamespace(id=f"b-{index}") for index in range(6)]

    async def fake_search_vector(_query, top_k):
        captured["vector_top_k"] = top_k
        return vector_docs

    def fake_search_bm25(_query, top_k):
        captured["bm25_top_k"] = top_k
        return bm25_docs

    kb = object.__new__(KnowledgeBase)
    kb._bm25 = SimpleNamespace(ready=True)
    kb.search_vector = fake_search_vector
    kb.search_bm25 = fake_search_bm25
    monkeypatch.setattr(retriever_module.settings, "hybrid_enabled", True)

    result = await kb.search_hybrid(
        "query", top_k=4, vector_top_k=5, bm25_top_k=6
    )

    assert captured == {"vector_top_k": 5, "bm25_top_k": 6}
    assert len(result) == 4


def test_reranker_reports_cloud_failure_instead_of_false_success(monkeypatch):
    class FailingCompressor:
        def rerank(self, *_args, **_kwargs):
            raise ValueError("service unavailable")

    docs = [SimpleNamespace(content="first"), SimpleNamespace(content="second")]
    reranker = Reranker()
    reranker._compressor = FailingCompressor()
    reranker._use_cloud = True
    monkeypatch.setattr(retriever_module.settings, "rerank_enabled", True)

    result, applied, error = reranker.rerank_with_status("query", docs, 1)

    assert result == docs[:1]
    assert applied is False
    assert error == "ValueError: service unavailable"
