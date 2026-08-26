import hashlib
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk
from app.rag.loader import parse_file
from app.rag.milvus_store import upset_chunk_vector
from app.rag.retriever import build_embedding, split_text
from app.services.chunk_service import save_document_with_chunks


async def save_file_to_db(
    path: Path,
    db: AsyncSession,
    title: str | None = None,
) -> list[Chunk]:
    """解析文件 → 分块 → 写 PG → embed → upsert Milvus。

    title 必须是上传原名（如 knowledge_base.md），不要用临时文件名。
    """
    file_name = title or path.name
    content = parse_file(path)
    chunks = split_text(file_name, content)
    texts = [c.page_content if hasattr(c, "page_content") else c for c in chunks]
    content_sha256 = hashlib.sha256(content.encode()).hexdigest()
    document_id, rows = await save_document_with_chunks(
        file_name, content_sha256, texts, db
    )
    embedder = build_embedding()
    for row in rows:
        vector = embedder.embed_query(row.content)
        upset_chunk_vector(row.id, document_id, vector)
    await db.commit()
    return rows


async def main():
    path = Path("data/knowledge_base.md")
    from app.database import AsyncSession as SessionFactory

    async with SessionFactory() as db:
        await save_file_to_db(path, db, title=path.name)


if __name__ == "__main__":
    import asyncio
    import sys

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
