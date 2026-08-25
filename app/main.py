import asyncio
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from app.config import settings
from app.database import engine, init_db
from app.rag.milvus_store import ensure_collection, get_milvus_client
from app.database import get_db
from app.rag.retriever import aanswer_with_rag
from app.schemas import ChatResponse, ChatRequest
from app.services.chat import chat
from app.services.session_service import get_sessions

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    ensure_collection()
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
if __name__ == "__main__":

    uvicorn.run(app, host="0.0.0.0", port=8000,loop="asyncio")