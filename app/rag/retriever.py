
from __future__ import annotations
import asyncio
import threading
import time
from typing import List, Tuple

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain.chat_models import init_chat_model
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter

from app.config import settings
from app.database import AsyncSession, get_db
from app.models import Chunk

from app.rag.fusion import reciprocal_rank_fusion
from app.rag.lexical import BM25Index
from pathlib import Path
from app.rag.milvus_store import search_vectors
from app.rag.reranker import Reranker
from app.services.chunk_service import get_chunks_by_ids
from app.services.resilience import ainvoke_with_retry
from rich import print as rprint
RAG_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "你是二手交易平台的智能客服助手。只能依据给定的资料回答问题；"
     "资料中没有的信息要如实说明不知道，禁止编造。回答使用简洁友好的中文。"),
    MessagesPlaceholder("history"),
    ("human", "资料：\n{context}\n\n问题：{question}"),
])


def build_llm():
    return init_chat_model(
            base_url=settings.AIROBOT_LLM_BASE_URL,
            api_key=settings.AIROBOT_LLM_API_KEY,
            model=settings.AIROBOT_LLM_MODEL,
            model_provider=settings.provider,
        )



async def _answer_with_rag_fresh_db(
    query: str, kb: KnowledgeBase, llm=None, history=None
) -> Tuple[str, List[str]]:
    """在独立 async session 中执行 RAG，供子线程 / asyncio.run 场景使用。"""
    async for db in get_db():
        kb._store = db
        return await aanswer_with_rag(query, kb, llm=llm, history=history)
    return ("知识库尚未初始化完成，请稍后再试。", [])


def answer_with_rag(
    query: str,
    kb: KnowledgeBase | None = None,
    llm=None,
    history=None,
) -> Tuple[str, List[str]]:
    """同步 RAG（Crew 工具等子线程场景）；内部新建 event loop + PG session。"""
    kb = kb or get_cached_kb()
    if kb is None:
        return ("知识库尚未初始化完成，请稍后再试。", [])
    return asyncio.run(_answer_with_rag_fresh_db(query, kb, llm=llm, history=history))


async def aanswer_with_rag(query: str, kb: KnowledgeBase, llm=None, history=None) -> Tuple[str, List[str]]:
    """混合检索（向量+BM25+RRF+rerank）+ RAG 生成，返回 (回答, 来源列表)。"""
    chunks = await kb.search(query)

    if not chunks:
        return ("未检索到相关知识，请尝试其他关键词。", [])

    document_content = "\n\n".join([c.content for c in chunks])
    chain = RAG_PROMPT | (llm or build_llm())
    answer = await ainvoke_with_retry(
        chain.ainvoke, {"context": document_content, "question": query, "history": history or []})
    if hasattr(answer, "content"):
        answer = answer.content
    sources = [f"{c.title}#{c.chunk_index}" for c in chunks]
    return answer, sources

async def aanswer_with_rag_stream(query: str, kb: KnowledgeBase, llm=None, history=None):
    """检索同 aanswer_with_rag，生成环节用 astream 逐 token yield。"""
    chunks = await kb.search(query)

    if not chunks:
        yield {"type": "token", "content": "未检索到相关知识，请尝试其他关键词。"}
        return
    document_content = "\n\n".join([c.content for c in chunks])
    chain = RAG_PROMPT | (llm or build_llm())
    sources = [f"{c.title}#{c.chunk_index}" for c in chunks]
    full_answer = ""
    async for chunk in chain.astream({"context": document_content, "question": query, "history": history or []}):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        full_answer += token
        yield {"type": "token", "content": token, "sources": sources}

def build_embedding()->DashScopeEmbeddings:
    # return OpenAIEmbeddings(
    #     model=settings.AIROBOT_EMBEDDING_MODEL,
    #     api_key=settings.AIROBOT_EMBEDDING_API_KEY,
    #     base_url=settings.AIROBOT_EMBEDDING_BASE_URL
    # )
    return DashScopeEmbeddings(
        dashscope_api_key=settings.AIROBOT_EMBEDDING_API_KEY,
        model=settings.AIROBOT_EMBEDDING_MODEL
    )

def build_splitter()->RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
    )

def build_markdown_splitter() -> MarkdownHeaderTextSplitter:
    """按 Markdown 标题层级切分（保留标题在正文中，增强检索上下文）。"""
    return MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3"), ("####", "H4")],
        strip_headers=False,
    )
def split_text(title: str, text: str) -> list[Document]:
    """按标题和内容切分文本，返回包含标题和内容的列表。"""
    splitter = build_splitter()

    if not (title.endswith(".md") or title.endswith(".markdown")):
        # 普通文本：直接切分
        chunks = splitter.split_text(text)
        return [Document(page_content=chunk, metadata={"source": title}) for chunk in chunks]
    md_splitter  = build_markdown_splitter()
    chapters = md_splitter.split_text(text)  # 返回 list[Document]

    result: list[Document] = []
    # 阈值：max(chunk_size * 2, chunk_size + 200)
    threshold = max(settings.chunk_size * 2, settings.chunk_size + 200)

    for chapter in chapters:
        page_content = chapter.page_content

        if len(page_content) > threshold:
            # 超长章节：用 RecursiveCharacterTextSplitter 二次切分
            sub_chunks = splitter.split_text(page_content)
            for sub in sub_chunks:
                result.append(Document(page_content=sub, metadata={"source": title}))
        else:
            # 正常长度：直接保留
            result.append(chapter)

    return result

class KnowledgeBase:
    def __init__(self, db: AsyncSession):
        self._splitter = build_splitter()
        self._markdown_splitter = build_markdown_splitter()
        self._bm25 = BM25Index()
        self._reranker = Reranker()
        self._documents: list[Chunk] = []  # 🔑 上层存业务对象（和BM25的_corpus一一对应）
        self._store = db

    @property
    def bm25_ready(self) -> bool:
        return self._bm25.ready

    @property
    def chunk_count(self) -> int:
        return len(self._documents)

    def _split_text(self, title: str, text: str) -> list[Document]:
        return split_text(title, text)

    def embed_query(self, query: str) -> list[float]:
        llm = build_embedding()
        query_vector = llm.embed_query(query)
        return query_vector

    async def build_index(self) -> None:
        """启动时全量构建：从 PG 加载所有 chunk，rebuild BM25（不是 append）。"""
        from app.services.chunk_service import list_all_chunks
        all_chunks = await list_all_chunks(self._store)
        self._documents = all_chunks
        self._bm25.rebuild([c.content for c in all_chunks])
        print(f"✅ 全量索引构建完成：共 {len(all_chunks)} 个chunk")

    async def ingest_file(self, path: Path, title: str | None = None) -> int:
        """入库并用原文件名作 title；返回本次新增块数。"""
        from app.rag.document_embedding import save_file_to_db
        try:
            new_chunks = await save_file_to_db(path, self._store, title=title)
        except Exception as e:
            print(f"❌ 持久化失败，跳过BM25更新: {e}")
            raise e
        self._documents.extend(new_chunks)
        self._bm25.add_documents([c.content for c in new_chunks])
        return len(new_chunks)

    async def search(self, query: str, top_k: int | None = None) -> list[Document]:
        """混合检索：向量 + BM25 -> RRF 融合 -> bge-reranker 重排。"""
        docs, _ = await self.search_detailed(query, top_k)
        return docs

    async def search_detailed(self, query: str, top_k: int | None = None) -> Tuple[list[Document], dict]:
        """混合检索并返回各阶段耗时明细，供控制台全链路可视化使用。

        返回 (docs, detail)，detail 字段：
        vector_ms / vector_hits / bm25_ms / bm25_hits / fusion_ms / fused /
        rerank_ms / rerank_enabled / hybrid。
        """
        top_k = top_k or settings.top_k
        detail = {"vector_ms": 0.0, "vector_hits": 0, "bm25_ms": 0.0, "bm25_hits": 0,
                  "fusion_ms": 0.0, "fused": 0, "rerank_ms": 0.0, "rerank_enabled": False,
                  "hybrid": bool(self._bm25.ready and settings.hybrid_enabled)}
        if not self._bm25.ready or not settings.hybrid_enabled:
            t0 = time.perf_counter()
            docs = await self.search_vector(query, top_k)
            detail["vector_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            detail["vector_hits"] = len(docs)
            return self._rerank_if_enabled(query, docs, top_k, detail), detail

        t0 = time.perf_counter()
        vector_docs = await self.search_vector(query, settings.hybrid_vector_top_k)
        detail["vector_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        detail["vector_hits"] = len(vector_docs)

        t0 = time.perf_counter()
        bm25_docs = self.search_bm25(query, settings.hybrid_bm25_top_k)
        detail["bm25_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        detail["bm25_hits"] = len(bm25_docs)

        t0 = time.perf_counter()
        fused_ids = reciprocal_rank_fusion(
            [[d.id for d in vector_docs],
             [d.id for d in bm25_docs]],
            top_k=settings.hybrid_fusion_top_k,
        )
        detail["fusion_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        detail["fused"] = len(fused_ids)

        doc_map = {d.id: d for d in vector_docs + bm25_docs}
        docs = [doc_map[did] for did in fused_ids if did in doc_map]
        return self._rerank_if_enabled(query, docs, top_k, detail), detail
    def _rerank_if_enabled(self, query: str, docs: list[Chunk], top_k: int,
                           detail: dict) -> list[Chunk]:

        if settings.rerank_enabled and self._reranker.ready:
            t0 = time.perf_counter()
            print(f"start reranking !!!!{len(docs)} docs")
            docs = self._reranker.rerank(query, docs, top_k)
            detail["rerank_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            detail["rerank_enabled"] = True
            print(f"end reranking !!!!{len(docs)} docs")
        return docs[:top_k]

    async def search_vector(self, query: str, top_k: int | None = None) -> list[Chunk]:
        """纯向量检索（对照用）。"""
        query_vector = self.embed_query(query)
        related_chunks = search_vectors(query_vector)
        chunk_ids = [chunk["chunk_id"] for chunk in related_chunks]
        chunk_texts = await get_chunks_by_ids(chunk_ids, self._store)
        return chunk_texts
    def search_bm25(self, query: str, top_k: int | None = None) -> list[Chunk]:
        """BM25检索：用BM25返回的下标映射上层的_documents，拿到业务对象"""
        indices = self._bm25.search(query, top_k)
        # 🔑 关键：用下标映射上层的_documents（不是BM25内部的_corpus）
        return [self._documents[i] for i in indices if i < len(self._documents)]

    async def search_hybrid(self, query: str, top_k: int | None = None) -> list[Chunk]:
        """RRF 融合（不含重排），供评测脚本与对照实验使用。"""
        top_k = top_k or settings.top_k
        if not self._bm25.ready or not settings.hybrid_enabled:
            return await self.search_vector(query, top_k)
        vector_docs = await self.search_vector(query, settings.hybrid_vector_top_k)
        from rich import print as rprint
        rprint("vectors::",vector_docs)
        bm25_docs = self.search_bm25(query, settings.hybrid_bm25_top_k)
        rprint("BM25:",bm25_docs)
        fused_ids = reciprocal_rank_fusion(
            [[d.id for d in vector_docs],
             [d.id for d in bm25_docs]],
            top_k=settings.hybrid_fusion_top_k,
        )
        chunk_map = {c.id: c for c in vector_docs + bm25_docs}
        docs = [chunk_map[cid] for cid in fused_ids if cid in chunk_map]
        # doc_map = {d.id: d for d in vector_docs + bm25_docs}
        return docs

_kb_instance: KnowledgeBase | None = None
_thread_kb = threading.local()


def bind_kb_for_crew(kb: KnowledgeBase) -> None:
    """Crew 在子线程跑工具时注入当前请求的 KB（避免 get_cached_kb 为空）。"""
    _thread_kb.kb = kb


def clear_kb_for_crew() -> None:
    _thread_kb.kb = None


def get_kb_instance(db: AsyncSession) -> KnowledgeBase:
    """全局单例；每次请求刷新 db，避免 lifespan 里的 session 关闭后失效。"""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KnowledgeBase(db)
    else:
        _kb_instance._store = db
    return _kb_instance


def get_cached_kb() -> KnowledgeBase | None:
    """优先 Crew 子线程注入的 KB，否则返回 lifespan/请求缓存的全局实例。"""
    kb = getattr(_thread_kb, "kb", None)
    if kb is not None:
        return kb
    return _kb_instance

if __name__ == "__main__":
    import asyncio
    from rich import print as rprint
    async def init():
        async for db in get_db():
            kb = get_kb_instance(db)
            await kb.build_index()
            print(f"✅ 测试初始化完成：共 {len(kb._documents)} 个chunk")
            answer, sources = await aanswer_with_rag("七天无理由", kb)
            rprint("RRF",answer)
            rprint("sources:",sources)
            answer2, sources2 = await aanswer_with_rag("你们老板叫什么", kb)
            rprint("RRF", answer2)
            rprint("sources:", sources2)


    asyncio.run(init())
    #