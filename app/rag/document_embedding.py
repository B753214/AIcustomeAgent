import hashlib
from pathlib import Path

from fastapi.params import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.rag.loader import parse_file
from app.rag.milvus_store import upset_chunk_vector
from app.rag.retriever import split_text, build_embedding
from app.services.chunk_service import save_document_with_chunks
from rich import print as rprint

async def ingest_file(path: Path, db: AsyncSession) -> None:
    content = parse_file(path)
    chunks = split_text(path.name, content)
    texts = [c.page_content if hasattr(c, "page_content") else c for c in chunks]
    content_sha256 = hashlib.sha256(content.encode()).hexdigest()
    document_id, rows = await save_document_with_chunks(path.name, content_sha256, texts, db)
    llm = build_embedding()
    for chunk_id, content in rows:
        embedding = llm.embed_query(content)
        upset_chunk_vector(chunk_id, document_id, embedding)
        rprint(f"Inserted chunk {chunk_id} with embedding {len(embedding)}")
    await db.commit()

async def main():
    path = Path("../db/knowledge_base.md")  # 从项目根目录算
    from app.database import AsyncSession as SessionFactory
    async with SessionFactory() as db:
        await ingest_file(path, db)
if __name__ == "__main__":
    import asyncio
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())