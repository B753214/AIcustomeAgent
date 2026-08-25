from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain.chat_models import init_chat_model
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter

from app.config import settings
from app.database import AsyncSession, get_db

from app.rag.milvus_store import search_vectors
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


async def aanswer_with_rag(query: str,db: AsyncSession, llm=None, history=None) -> str:
    """使用 RAG 模型回答用户问题。"""
    llm = build_embedding()
    query_vector = llm.embed_query(query)
    # 检索最相关的文档
    related_chunks = search_vectors(query_vector)
    chunk_ids = [chunk["chunk_id"] for chunk in related_chunks]
    chunk_text = await get_chunks_by_ids(chunk_ids, db)

    # 合并所有文档内容
    document_content = "\n\n".join([doc.content for doc in chunk_text])
    chain = RAG_PROMPT | build_llm()
    answer = await ainvoke_with_retry(
        chain.ainvoke, {"context": document_content, "question": query, "history": history or []})
    sources = [f"{d.title}#{d.chunk_index}" for d in chunk_text]
    return answer, sources
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

if __name__ == "__main__":
    from app.rag.loader import parse_file
    from pathlib import Path
    from rich import print as rprint