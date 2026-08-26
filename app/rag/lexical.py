from typing import List

import jieba
from rank_bm25 import BM25Okapi


def tokenize(text: str) -> List[str]:
    return [t for t in jieba.lcut(text) if t.strip()]


class BM25Index:
    def __init__(self) -> None:
        self._corpus: List[str] = []
        self._bm25: BM25Okapi | None = None

    @property
    def ready(self) -> bool:
        return self._bm25 is not None

    def rebuild(self, texts: List[str]) -> None:
        """全量重建（启动从 PG 加载时用），禁止在已有语料上再 extend。"""
        self._corpus = list(texts)
        if not self._corpus:
            self._bm25 = None
            return
        self._bm25 = BM25Okapi([tokenize(t) for t in self._corpus])

    def add_documents(self, texts: List[str]) -> None:
        """追加语料后重建索引（ingest 热更新）。"""
        if not texts:
            return
        self._corpus.extend(texts)
        self._bm25 = BM25Okapi([tokenize(t) for t in self._corpus])

    def search(self, query: str, top_k: int) -> List[int]:
        """返回按 BM25 得分排序的文档索引列表（仅保留得分>0 的命中）。"""
        if not self.ready or not self._corpus:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [i for i in order if scores[i] > 0][:top_k]
