import os
from typing import List

from langchain_core.documents import Document

from app.config import settings
from app.models import Chunk


class Reranker:
    def __init__(self):
        self._model = None
        self._compressor = None
        self._use_cloud = False

    @property
    def ready(self) -> bool:
        if not settings.rerank_enabled:
            return False

        if self._compressor is not None and self._use_cloud:
            return True
        if self._model is not None and not self._use_cloud:
            return True

        if settings.rerank_provider == "dashscope":
            try:
                # api_key = (
                #     settings.rerank_api_key
                #     or settings.AIROBOT_EMBEDDING_API_KEY
                #     or settings.embedding_api_key
                # )
                # os.environ["DASHSCOPE_API_KEY"] = api_key
                import dashscope
                from langchain_community.document_compressors import DashScopeRerank
                self._compressor = DashScopeRerank(
                    client=dashscope.TextReRank,
                    model=settings.rerank_model,
                    top_n=settings.top_k,
                    dashscope_api_key=settings.rerank_api_key,
                )
                self._use_cloud = True
                return True
            except Exception:
                pass

        try:
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(
                settings.rerank_model, max_length=512, local_files_only=True)
            self._use_cloud = False
            return True
        except Exception:
            return False

    def rerank(self, query: str, docs: List[Chunk], top_k: int) -> List[Chunk]:
        print(f"Reranker::rerank", self.ready, self._use_cloud)
        if not docs:
            return []
        if not self.ready:
            return docs[:top_k]

        if self._use_cloud:
            return self._rerank_cloud(query, docs, top_k)
        else:
            return self._rerank_local(query, docs, top_k)

    def _rerank_cloud(self, query: str, docs: List[Chunk], top_k: int) -> List[Chunk]:
        contents = [d.content for d in docs]
        try:
            rankings = self._compressor.rerank(contents, query, top_n=top_k)
            result = []
            seen = set()
            from rich import print as rprint
            rprint("rankings:", rankings)
            for r in rankings:
                idx = r["index"]
                if idx not in seen and idx < len(docs):
                    result.append(docs[idx])
                    seen.add(idx)
            for i, d in enumerate(docs):
                if i not in seen:
                    result.append(d)
                if len(result) >= top_k:
                    break
            return result[:top_k]
        except Exception:
            return docs[:top_k]

    def _rerank_local(self, query: str, docs: List[Chunk], top_k: int) -> List[Chunk]:
        try:
            pairs = [(query, d.content) for d in docs]
            scores = self._model.predict(pairs)
            ranked = sorted(zip(docs, scores), key=lambda x: float(x[1]), reverse=True)
        except Exception:
            return docs[:top_k]
        return [d for d, _ in ranked[:top_k]]