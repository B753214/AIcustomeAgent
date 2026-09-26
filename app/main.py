import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from app.agents.alarm import run_alarm_agent_stream
from app.agents.alarm.runner import run_alarm_agent
from app.harness.adapter.alarm_http import alarm_harness_http
from app.harness.adapter.chat_http import chat_harness_http, chat_harness_stream
from app.harness.adapter.knowledge_http import knowledge_harness_http
from app.harness.adapter.run_http import event_to_dict, run_to_dict
from app.harness.runtime.cancellation import CancellationToken
from app.harness_storage import get_run, list_events
from app.services.auth import get_user_id, verify_api_key
from app.services.ratelimit import limiter
import uvicorn
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException,Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse, StreamingResponse, HTMLResponse, FileResponse

from app.agents.tools import CREW_TOOLS_READY
from app.config import PROJECT_ROOT, settings
from app.database import engine, init_db, get_db
from app.rag.milvus_store import ensure_collection, get_milvus_client
from app.rag.retriever import aanswer_with_rag, get_kb_instance
from app.schemas import ChatResponse, ChatRequest, IngestResponse, StatsResponse
from app.services.chat import chat, run, run_astream
from app.services.chunk_service import document_exists_by_name
from app.services.semantic_cache import semantic_cache
from app.services.session_service import (
    get_sessions,
    load_session_history,
    create_session as _create_session,
    get_session,
    end_session,
    clear_session_history,
    archive_session,
    soft_delete_session,
)
from app.services.tracing import traces

SAMPLE_KB = PROJECT_ROOT / "data" / "knowledge_base.md"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
    except Exception as exc:
        raise RuntimeError(
            "PostgreSQL 不可用（本服务必选依赖）。"
            "请检查 POSTGRES_URI（须 postgresql+asyncpg://...），"
            "或先执行: docker compose up -d postgres。"
            f" 原因: {exc}"
        ) from exc
    try:
        ensure_collection()
    except Exception as exc:
        raise RuntimeError(
            "Milvus 不可用（本服务必选依赖，无内存向量降级）。"
            "请检查 MILVUS_URI（不是 AIROBOT_MILVUS_URI），"
            "或先执行: docker compose up -d milvus-standalone。"
            f" 原因: {exc}"
        ) from exc
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

app = FastAPI(title="智能运维 Agent 助手", version=settings.APP_VERSION, lifespan=lifespan)

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
    """基础设施健康检查：PostgreSQL 与 Milvus 均为必选，双 ok 才返回 200。

    详见 docs/deps.md。不探测 LLM/Embedding 连通性。
    """
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
            "dependencies": {
                "postgres": {
                    "required": True,
                    "status": "ok" if pg_status == "ok" else "unreachable",
                    "detail": pg_status,
                },
                "milvus": {
                    "required": True,
                    "status": "ok" if milvus_status == "ok" else "unreachable",
                    "detail": milvus_status,
                },
            },
            "llm_model": settings.AIROBOT_LLM_MODEL,
            "embedding_model": getattr(
                settings, "AIROBOT_EMBEDDING_MODEL", settings.embedding_model
            ),
        },
    )


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat_ep(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
    user_id: str = Depends(get_user_id),
):
    kb = get_kb_instance(db)
    try:
        if settings.harness_runtime:
            return await chat_harness_http(req, kb, db, user_id=user_id)
        result = await run(req.message, req.session_id, kb, db, user_id=user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc) or "会话不可写入") from exc
    return ChatResponse(**{k: v for k, v in result.items() if k in ChatResponse.model_fields})


@app.post("/sessions")
async def session_memory(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_user_id),
):
    session_list = await get_sessions(db, user_id)
    return [
        {
            "session_id": s.session_id,
            "user_id": s.user_id,
            "status": getattr(s, "status", None),
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if getattr(s, "updated_at", None) else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        }
        for s in session_list
    ]


@app.get("/dashboard")
async def dashboard():
    """旧版单页控制台（app/static/dashboard.html）。"""
    html = (PROJECT_ROOT / "app" / "static" / "dashboard.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/console")
@app.get("/console/")
@app.get("/console/{full_path:path}")
async def react_console(full_path: str = ""):
    """React 18 控制台（frontend/dist）；需先在 frontend 目录执行 npm run build。"""
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        return HTMLResponse(
            "<!DOCTYPE html><html><body style='font-family:sans-serif;padding:24px'>"
            "<h2>React 控制台尚未构建</h2>"
            "<p>请执行：</p>"
            "<pre>cd frontend\nnpm install\nnpm run build</pre>"
            "<p>或开发态：<code>npm run dev</code> 后访问 Vite 地址（默认 :5173）。</p>"
            "<p><a href='/dashboard'>返回旧版控制台</a></p>"
            "</body></html>",
            status_code=503,
        )
    # SPA：非静态资源一律回退到 index.html
    candidate = FRONTEND_DIST / full_path if full_path else index
    if full_path and candidate.is_file() and ".." not in Path(full_path).parts:
        return FileResponse(candidate)
    return FileResponse(index)


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
async def create_session_ep(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_user_id),
):
    import uuid
    sid = str(uuid.uuid4())
    session = await _create_session(sid, user_id, db)
    return {"session_id": session.session_id, "user_id": session.user_id}


@app.get("/api/v1/sessions/{session_id}/history")
async def session_history(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_user_id),
):
    from app.services.session_service import get_session

    owned = await get_session(session_id, user_id, db)
    if owned is None or owned.status == "deleted":
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    messages = await load_session_history(
        session_id, user_id, db, create_if_missing=False
    )
    return {"session_id": session_id, "user_id": user_id, "messages": messages}


@app.get("/retrieval/{query}")
async def retrieval(query: str, db: AsyncSession = Depends(get_db)):
    kb = get_kb_instance(db)
    if settings.harness_runtime:
        return await knowledge_harness_http(query, kb)
    else:
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


def _legacy_agent_chunk_to_wire(chunk: dict) -> dict:
    """旧 Agent chunk → 标准 SSE 帧（harness_runtime 关闭时的 chat 流）。"""
    t = chunk.get("type")
    if t == "stage":
        return {
            "type": "workflow.step",
            "stage": chunk.get("stage"),
            "message": chunk.get("msg") or chunk.get("message"),
            "ok": chunk.get("ok"),
            "ms": chunk.get("ms"),
        }
    if t == "token":
        return {"type": "model.token", "content": chunk.get("content") or ""}
    if t in ("done", "result"):
        meta = dict(chunk.get("meta") or {})
        return {
            "type": "run.completed",
            "output": chunk.get("reply") or chunk.get("output") or "",
            "sources": chunk.get("sources") or [],
            "metadata": {
                **meta,
                "intent": chunk.get("intent") or meta.get("intent"),
                "engine": chunk.get("engine") or meta.get("engine"),
                "cache_hit": chunk.get("cache_hit", meta.get("cache_hit", False)),
                "used_crew": chunk.get("used_crew", meta.get("used_crew", False)),
            },
        }
    if t == "error":
        return {
            "type": "run.failed",
            "message": chunk.get("message") or chunk.get("msg") or "error",
        }
    if t == "intent":
        return {
            "type": "workflow.step",
            "stage": "intent",
            "message": f"意图识别为 {chunk.get('intent')}",
            "ok": True,
        }
    return chunk


@app.post("/api/v1/chat/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
    user_id: str = Depends(get_user_id),
):
    # H2-5：Depends(get_db) 仍会随 StreamingResponse 活到流结束（长持有）。
    # Harness 落库已走 options.session_factory 短事务；完全拆掉 Depends 可后续再收。
    # 开关开：Runtime SSE；关：旧 run_astream。
    _sse_headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    kb = get_kb_instance(db)

    if settings.harness_runtime:
        token = CancellationToken()

        async def gen_harness():
            try:
                async for chunk in chat_harness_stream(
                    req, kb, db, cancellation_token=token, user_id=user_id
                ):
                    if await request.is_disconnected():
                        token.cancel()
                        break
                    yield _sse(chunk)
            except PermissionError as exc:
                yield _sse({"type": "error", "detail": str(exc) or "会话不可写入"})
            finally:
                token.cancel()

        return StreamingResponse(
            gen_harness(),
            media_type="text/event-stream",
            headers=_sse_headers,
        )

    async def gen_legacy():
        try:
            async for chunk in run_astream(
                req.message, req.session_id, kb, db, user_id=user_id
            ):
                yield _sse(_legacy_agent_chunk_to_wire(chunk))
        except PermissionError as exc:
            yield _sse({"type": "error", "detail": str(exc) or "会话不可写入"})

    return StreamingResponse(
        gen_legacy(),
        media_type="text/event-stream",
        headers=_sse_headers,
    )

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
        from app.harness.adapter.alarm_http import alarm_harness_stream

        try:
            yield _sse({"type": "workflow.step", "message": "开始分析...", "stage": "alarm"})
            analyze_input = content
            raw_url = extract_monitor_url(content)
            if not raw_url:
                yield _sse({
                    "type": "workflow.step",
                    "message": "正在理解你的问题...",
                    "stage": "alarm",
                })
                resolved_url = None
                chat_reply = None
                async for ev in iter_resolve_analyze_url(content):
                    et = ev.get("type")
                    if et == "token":
                        yield _sse({
                            "type": "model.token",
                            "content": ev.get("content") or "",
                        })
                    elif et == "error":
                        yield _sse(
                            {
                                "type": "run.failed",
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
                            "type": "workflow.step",
                            "message": "已识别监控参数，开始获取数据...",
                            "stage": "alarm_fetch",
                        }
                    )
                else:
                    yield _sse({
                        "type": "run.completed",
                        "output": chat_reply or "",
                    })
                    yield "data: [DONE]\n\n"
                    return

            if settings.harness_runtime:
                token = CancellationToken()
                try:
                    async for chunk in alarm_harness_stream(
                        analyze_input, cancellation_token=token
                    ):
                        if await request.is_disconnected():
                            token.cancel()
                            break
                        yield _sse(chunk)
                finally:
                    token.cancel()
            else:
                async for ev in run_alarm_agent_stream(analyze_input):
                    et = ev.get("type")
                    if et == "stage":
                        yield _sse({
                            "type": "workflow.step",
                            "message": ev.get("msg") or "",
                            "stage": ev.get("stage") or "alarm",
                            "ok": ev.get("ok"),
                        })
                    elif et == "token":
                        yield _sse({
                            "type": "model.token",
                            "content": ev.get("content") or "",
                        })
                    elif et == "done":
                        payload = {
                            "type": "run.completed",
                            "output": ev.get("reply") or "",
                            "metadata": ev.get("meta") or {},
                        }
                        if ev.get("skip"):
                            payload["metadata"] = {
                                **(payload["metadata"] or {}),
                                "skip": True,
                            }
                        yield _sse(payload)
                    else:
                        yield _sse(ev)
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield _sse({"type": "run.failed", "message": str(e)})
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

@app.post("/api/v1/alarm")
async def alarm_ep(req: ChatRequest, _: None = Depends(verify_api_key)):
    if settings.harness_runtime:
        return await alarm_harness_http(req.message)
    res = await run_alarm_agent(req.message)
    return {
        "reply": res.get("reply") or "",
        "sources": res.get("sources") or [],
        "intent": res.get("intent"),
        "engine": res.get("engine", "alarm"),
    }

@app.get("/api/v1/harness/runs/{run_id}")
async def harness_runs_ep(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    """按 run_id 回放：Run 台账 + 有序事件列表。"""
    row = await get_run(db, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="运行不存在")
    events = await list_events(db, run_id)
    return {
        "run": run_to_dict(row),
        "events": [event_to_dict(e) for e in events],
    }
def _session_public(s) -> dict:
    return {
        "session_id": s.session_id,
        "user_id": s.user_id,
        "status": s.status,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        "ended_at": s.ended_at.isoformat() if s.ended_at else None,
    }


@app.post("/api/v1/sessions")
async def create_sessions_ep(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_user_id),
    _: None = Depends(verify_api_key),
):
    import uuid

    sid = str(uuid.uuid4())
    session = await _create_session(sid, user_id, db)
    return _session_public(session)


@app.get("/api/v1/sessions")
async def list_sessions_ep(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_user_id),
    _: None = Depends(verify_api_key),
):
    session_list = await get_sessions(db, user_id)
    return [_session_public(s) for s in session_list]


@app.post("/api/v1/sessions/{session_id}/end")
async def end_sessions_ep(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_user_id),
    _: None = Depends(verify_api_key),
):
    session = await end_session(session_id, user_id, db)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    return _session_public(session)


@app.post("/api/v1/sessions/{session_id}/archive")
async def archive_sessions_ep(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_user_id),
    _: None = Depends(verify_api_key),
):
    session = await archive_session(session_id, user_id, db)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    return _session_public(session)


@app.post("/api/v1/sessions/{session_id}/clear")
async def clear_sessions_ep(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_user_id),
    _: None = Depends(verify_api_key),
):
    session = await get_session(session_id, user_id, db)
    if session is None or session.status == "deleted":
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    n = await clear_session_history(session_id, user_id, db)
    return {"session_id": session_id, "cleared": n, "status": session.status}


@app.delete("/api/v1/sessions/{session_id}")
async def delete_sessions_ep(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_user_id),
    _: None = Depends(verify_api_key),
):
    session = await soft_delete_session(session_id, user_id, db)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    return _session_public(session)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
