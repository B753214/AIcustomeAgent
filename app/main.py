import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from app.agents.alarm import run_alarm_agent_stream
from app.services.auth import verify_api_key
from app.services.ratelimit import limiter
import uvicorn
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException,Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse, StreamingResponse, HTMLResponse

from app.agents.tools import CREW_TOOLS_READY
from app.config import PROJECT_ROOT, settings
from app.database import engine, init_db, get_db
from app.rag.milvus_store import ensure_collection, get_milvus_client
from app.rag.retriever import aanswer_with_rag, get_kb_instance
from app.schemas import ChatResponse, ChatRequest, IngestResponse, StatsResponse
from app.services.chat import chat, run, run_astream
from app.services.chunk_service import document_exists_by_name
from app.services.semantic_cache import semantic_cache
from app.services.session_service import get_sessions, load_session_history, create_session as _create_session
from app.services.tracing import traces

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

def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # 格式常为 "真实客户端, 代理1, 代理2" → 取第一个
        return forwarded.split(",")[0].strip()
    if request.headers.get("x-real-ip"):
        return request.headers.get("x-real-ip")
    return request.client.host if request.client else "unknown"

app = FastAPI(title="智能客服", version=settings.APP_VERSION, lifespan=lifespan)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if settings.ratelimit_enabled and request.url.path.startswith("/api/v1"):
        # 白名单：stats / traces 放行（你现在还没有这俩接口，先写上）
        if request.url.path not in ("/api/v1/stats", "/api/v1/traces"):
            client_ip = _client_ip(request)
            if not limiter.allow(client_ip):
                traces.record({
                    "message": f"{request.method} {request.url.path}",
                    "session_id": client_ip,
                    "intent": "ratelimited",
                    "status": 429,
                    "total_ms": 0,
                })
                return JSONResponse(
                    status_code=429,
                    content={"detail": "请求过于频繁，请稍后再试。"},
                )
    return await call_next(request)

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
async def chat_ep(req: ChatRequest, db: AsyncSession = Depends(get_db), _: None = Depends(verify_api_key)):
    kb = get_kb_instance(db)
    result = await run(req.message, req.session_id, kb, db)
    return ChatResponse(**result)


@app.post("/sessions")
async def session_memory(db: AsyncSession = Depends(get_db)):
    session_list = await get_sessions(db)
    return [
        {
            "session_id": s.session_id,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        }
        for s in session_list
    ]


@app.get("/dashboard")
async def dashboard():
    html = (PROJECT_ROOT / "app" / "static" / "dashboard.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.post("/login")
@app.get("/login")
async def alarm_browser_login():
    """触发 info-plate 浏览器登录（Day8；SMS/扫码见 Day11）。"""
    if not settings.alarm_browser_enabled:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "alarm_browser_enabled=false"},
        )
    try:
        from app.agents.alarm.browser import ensure_logged_in

        ok = await ensure_logged_in()
        return {
            "ok": ok,
            "message": "登录成功" if ok else "登录失败（检查账号/密码，或需 SMS/扫码）",
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(e)},
        )


@app.get("/create_session")
async def create_session_ep(db: AsyncSession = Depends(get_db)):
    import uuid
    sid = str(uuid.uuid4())
    session = await _create_session(sid, db)
    return {"session_id": session.session_id}


@app.get("/api/v1/sessions/{session_id}/history")
async def session_history(session_id: str, db: AsyncSession = Depends(get_db)):
    messages = await load_session_history(session_id, db)
    return {"session_id": session_id, "messages": messages}


@app.get("/retrieval/{query}")
async def retrieval(query: str, db: AsyncSession = Depends(get_db)):
    kb = get_kb_instance(db)
    answer, sources = await aanswer_with_rag(query, kb)
    return {"reply": answer, "sources": sources}


@app.post("/api/v1/ingest", response_model=IngestResponse, )
async def ingest(file: UploadFile = File(...), db: AsyncSession = Depends(get_db), _: None = Depends(verify_api_key)):
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

def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

@app.post("/api/v1/chat/stream")
async def chat_stream(req: ChatRequest, db: AsyncSession = Depends(get_db), _: None = Depends(verify_api_key)):
    kb = get_kb_instance(db)

    async def gen():
        async for chunk in run_astream(req.message, req.session_id, kb, db):
            yield _sse(chunk)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},)

@app.get("/api/v1/stats", response_model=StatsResponse)
async def stats_ep(db: AsyncSession = Depends(get_db)):
    kb = get_kb_instance(db)
    cache = semantic_cache.stats()
    rl = limiter.stats()
    return StatsResponse(
        total_chunks=kb.chunk_count,
        llm_model=settings.AIROBOT_LLM_MODEL,
        embedding_model=settings.AIROBOT_EMBEDDING_MODEL,
        use_crew=settings.use_crew,
        crew_available=CREW_TOOLS_READY,
        hybrid_enabled=settings.hybrid_enabled,
        bm25_ready=kb.bm25_ready,
        rerank_enabled=settings.rerank_enabled,
        cache_enabled=settings.cache_enabled,
        cache_size=cache["size"],
        cache_hits=cache["hits"],
        cache_misses=cache["misses"],
        cache_threshold=settings.cache_threshold,
        ratelimit_enabled=settings.ratelimit_enabled,
        ratelimit_per_minute=rl["limit_per_minute"],
        ratelimit_blocked=rl["blocked"],
    )

@app.get("/api/v1/traces")
def traces_ep(limit: int = 50):
    return {"entries": traces.recent(limit), "summary": traces.summary()}

@app.post("/api/analyze")
async def api_analyze(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="无效 JSON")
    content = (body.get("content") or body.get("url") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="请提供 content 或 url 参数")

    async def gen():
        from app.agents.alarm.chat_intent import iter_resolve_analyze_url
        from app.agents.alarm.parse import extract_monitor_url

        try:
            yield _sse({"type": "progress", "message": "开始分析..."})
            analyze_input = content
            raw_url = extract_monitor_url(content)
            if not raw_url:
                yield _sse({"type": "progress", "message": "正在理解你的问题..."})
                resolved_url = None
                chat_reply = None
                async for ev in iter_resolve_analyze_url(content):
                    et = ev.get("type")
                    if et == "token":
                        yield _sse({"type": "chunk", "content": ev.get("content") or ""})
                    elif et == "error":
                        yield _sse(
                            {
                                "type": "error",
                                "message": ev.get("message") or "AI 回复失败",
                            }
                        )
                        yield "data: [DONE]\n\n"
                        return
                    elif et == "result":
                        resolved_url = ev.get("url")
                        chat_reply = ev.get("chat_reply")
                if resolved_url:
                    analyze_input = resolved_url
                    yield _sse(
                        {
                            "type": "progress",
                            "message": "已识别监控参数，开始获取数据...",
                        }
                    )
                else:
                    yield _sse({"type": "done", "report": chat_reply or ""})
                    yield "data: [DONE]\n\n"
                    return

            async for ev in run_alarm_agent_stream(analyze_input):
                et = ev.get("type")
                if et == "stage":
                    yield _sse({"type": "progress", "message": ev.get("msg") or ""})
                elif et == "token":
                    yield _sse({"type": "chunk", "content": ev.get("content") or ""})
                elif et == "done":
                    payload = {
                        "type": "done",
                        "report": ev.get("reply") or "",
                        "meta": ev.get("meta") or {},
                    }
                    if ev.get("skip"):
                        payload["skip"] = True
                    yield _sse(payload)
                else:
                    yield _sse(ev)
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",  # 工作台跨端口时需要；若已有全局 CORS 可去掉
        },
    )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
