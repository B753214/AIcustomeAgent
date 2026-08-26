import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from app.config import settings
from app.database import engine, init_db
from app.rag.milvus_store import ensure_collection, get_milvus_client
from app.database import get_db
from app.rag.retriever import aanswer_with_rag, get_kb_instance, KnowledgeBase
from app.schemas import ChatResponse, ChatRequest, IngestResponse
from app.services.chat import chat
from app.services.session_service import get_sessions


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    ensure_collection()
    await engine.dispose()
    async for db in get_db():
        # ② 获取全局单例（第一次调用会初始化，后续调用复用）
        kb = get_kb_instance(db)
        # ③ 执行全量加载（从PG读所有chunk，构建BM25内存索引）
        await kb.build_index()
        print("✅ KnowledgeBase 初始化完成：PG/Milvus/BM25 全部就绪")
        break  # 只需要一个DB会话，用完退出循环

        # 2. 服务就绪，开始接收请求
    yield
    await engine.dispose()

app=FastAPI(title="智能客服", version=settings.APP_VERSION, lifespan=lifespan)
@app.get("/health")
async def health():
    pg_status="ok"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            pg_status="ok"
    except Exception as e:
        pg_status=f"unreachable: {str(e)}"
    milvus_status="ok"
    try:
        client = get_milvus_client()
        client.list_collections()
    except Exception as e:
        milvus_status=f"unreachable: {str(e)}"
    is_healthy= (pg_status=="ok") and (milvus_status=="ok")
    status_code = 200 if is_healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if is_healthy else "unhealthy",
            "postgres": pg_status,
            "milvus": milvus_status,
            "llm_model": settings.AIROBOT_LLM_MODEL,
            "embedding_model": settings.embedding_model
        }
    )

@app.post("/api/v1/chat",response_model=ChatResponse)
async def chat_ep(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    result = await chat(req.message, req.session_id, db)
    return ChatResponse(**result)

@app.post("/sessions")
async def session_memory(db: AsyncSession = Depends(get_db)):
    sessionList = await get_sessions(db)
    return sessionList

@app.get("/create_session")
async def create_session(db: AsyncSession = Depends(get_db)):
    session = await create_session(db)
    return session

@app.get("/retrieval/{query}")
async def retrieval(query: str, db: AsyncSession = Depends(get_db)):
    result = await aanswer_with_rag(query, db)
    return result
@app.post("/api/v1/ingest", response_model=IngestResponse)
async def ingest(file: UploadFile = File(...)):
    if not settings.embedding_api_key:
        raise HTTPException(status_code=400, detail="未配置 AIROBOT_EMBEDDING_API_KEY，无法向量化入库")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".docx", ".md", ".txt", ".markdown"):
        raise HTTPException(status_code=400, detail="仅支持 pdf / docx / md / txt")
    content = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        chunks = kb.ingest_file(tmp_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"解析失败: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    return IngestResponse(file_name=file.filename or "unknown",
                          chunks=chunks, total_chunks=kb.chunk_count)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)