import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from app.config import PROJECT_ROOT, settings
from app.database import engine, init_db, get_db
from app.rag.milvus_store import ensure_collection, get_milvus_client
from app.rag.retriever import aanswer_with_rag, get_kb_instance
from app.schemas import ChatResponse, ChatRequest, IngestResponse
from app.services.chat import chat, run
from app.services.chunk_service import document_exists_by_name
from app.services.session_service import get_sessions

SAMPLE_KB = PROJECT_ROOT / "data" / "knowledge_base.md"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    ensure_collection()
    async for db in get_db():
        kb = get_kb_instance(db)
        if SAMPLE_KB.exists():
            if await document_exists_by_name(SAMPLE_KB.name, db):
                print(f"示例库已存在，跳过导入: {SAMPLE_KB.name}")
            else:
                n = await kb.ingest_file(SAMPLE_KB, title=SAMPLE_KB.name)
                print(f"已导入示例库 {SAMPLE_KB.name}: {n} chunks")
        else:
            print(f"未找到示例库文件，跳过: {SAMPLE_KB}")
        await kb.build_index()
        print("✅ KnowledgeBase 初始化完成：PG/Milvus/BM25 全部就绪")
        break
    yield
    await engine.dispose()


app = FastAPI(title="智能客服", version=settings.APP_VERSION, lifespan=lifespan)


@app.get("/health")
async def health():
    pg_status = "ok"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            pg_status = "ok"
    except Exception as e:
        pg_status = f"unreachable: {str(e)}"
    milvus_status = "ok"
    try:
        client = get_milvus_client()
        client.list_collections()
    except Exception as e:
        milvus_status = f"unreachable: {str(e)}"
    is_healthy = (pg_status == "ok") and (milvus_status == "ok")
    status_code = 200 if is_healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if is_healthy else "unhealthy",
            "postgres": pg_status,
            "milvus": milvus_status,
            "llm_model": settings.AIROBOT_LLM_MODEL,
            "embedding_model": getattr(
                settings, "AIROBOT_EMBEDDING_MODEL", settings.embedding_model
            ),
        },
    )


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat_ep(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    kb = get_kb_instance(db)
    result = await run(req.message, req.session_id, kb, db)
    return ChatResponse(**result)


@app.post("/sessions")
async def session_memory(db: AsyncSession = Depends(get_db)):
    session_list = await get_sessions(db)
    return session_list


@app.get("/create_session")
async def create_session(db: AsyncSession = Depends(get_db)):
    session = await create_session(db)
    return session


@app.get("/retrieval/{query}")
async def retrieval(query: str, db: AsyncSession = Depends(get_db)):
    kb = get_kb_instance(db)
    answer, sources = await aanswer_with_rag(query, kb)
    return {"reply": answer, "sources": sources}


@app.post("/api/v1/ingest", response_model=IngestResponse)
async def ingest(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    kb = get_kb_instance(db)
    api_key = settings.AIROBOT_EMBEDDING_API_KEY or settings.embedding_api_key
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="未配置 Embedding API Key，无法向量化入库",
        )
    original_name = file.filename or "upload.bin"
    suffix = Path(original_name).suffix.lower()
    if suffix not in (".pdf", ".docx", ".md", ".txt", ".markdown"):
        raise HTTPException(status_code=400, detail="仅支持 pdf / docx / md / txt")
    content = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        # 临时路径只读内容；title 必须用上传原名
        n = await kb.ingest_file(tmp_path, title=original_name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"解析失败: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    return IngestResponse(
        file_name=original_name,
        chunks=n,
        total_chunks=kb.chunk_count,
    )
# @app.post("/api/v1/chat/stream")
# async def chat_stream(req: ChatRequest, db: AsyncSession = Depends(get_db)):
#     kb = get_kb_instance(db)
#     return await chat(req.message, req.session_id, db, stream=True)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
