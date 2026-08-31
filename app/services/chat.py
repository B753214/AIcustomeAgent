import asyncio
import time
from enum import StrEnum

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from pydantic import Field, BaseModel

from app.agents.alarm import is_alarm_message
from app.agents.alarm.runner import run_alarm_agent, run_alarm_agent_stream
from app.agents.crew import run_crew
from app.agents.tools import query_order, CREW_TOOLS_READY
from app.config import settings
from app.rag.retriever import (
    aanswer_with_rag,
    bind_kb_for_crew,
    clear_kb_for_crew,
    get_kb_instance,
    KnowledgeBase,
    aanswer_with_rag_stream,
)
from app.services.resilience import ainvoke_with_retry
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.semantic_cache import semantic_cache
from app.services.session_service import load_session_history, save_message, clear_session_history, save_turn, \
    get_sessions
from app.services.tracing import traces

_llm_cache: dict = {}
class IntentEnum(StrEnum):
    ALARM = "alarm"
    KNOWLEDGE = "knowledge"  # 知识问答
    ORDER = "order"          # 订单查询
    CHAT = "chat"            # 闲聊
    UNKNOWN = "unknown"      # 未知意图

INTENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "你是意图分类器，只输出 JSON："
     "{{\"intent\": \"alarm|knowledge|order|chat|unknown\", \"confidence\": 0.7, \"reason\": \"简短理由\"}}。"
     "规则："
     "1) 同时含告警字段（如【指标】/【配置ID】）与 info-plate 监控链接 → alarm；"
     "2) 明确查订单号/物流状态 → order；"
     "3) 退货/售后/运费/规则等平台知识（无具体订单号）→ knowledge；"
     "4) 打招呼闲聊 → chat。"
     "不要把「怎么申请退货」判成 order。"),
    MessagesPlaceholder("history"),
    ("human", "{message}"),
])

CHAT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是二手交易平台智能客服，语气友好简洁…"),
    MessagesPlaceholder("history"),
    ("human", "{message}"),
])

class Classifier(BaseModel):
    intent: IntentEnum = Field(IntentEnum.KNOWLEDGE, description="意图分类，可选值：alarm（监控告警排查）/knowledge（知识问答）/order（订单查询）/chat（闲聊）/unknown（未知）")
    confidence: float = Field(description="0~1置信分数")
    reason: str=Field(default="", description="输出分类原因")

def get_llm()->BaseChatModel:
    key = (settings.AIROBOT_LLM_MODEL, settings.AIROBOT_LLM_BASE_URL, settings.AIROBOT_LLM_API_KEY)
    if key not in _llm_cache:
        _llm_cache[key] = init_chat_model(
            base_url=settings.AIROBOT_LLM_BASE_URL,
            api_key=settings.AIROBOT_LLM_API_KEY,
            model=settings.AIROBOT_LLM_MODEL,
            model_provider=settings.provider,
        )
    return _llm_cache[key]

def _to_langchain_messages(history: list[dict]) -> list:
    """将 {"role","content"} 字典列表转为 LangChain Message 对象列表"""
    return [
        HumanMessage(content=m["content"]) if m["role"] == "user"
        else AIMessage(content=m["content"])
        for m in history
    ]

async def classify_intent(message: str, history: list) -> IntentEnum:
    try:
        llm_struct = get_llm().with_structured_output(Classifier)
        # 兼容：如果传入的仍是 dict，先转为 LangChain Message
        lc_history = _to_langchain_messages(history) if history and isinstance(history[0], dict) else history
        response = await ainvoke_with_retry(
            llm_struct.ainvoke,
            INTENT_PROMPT.format_messages(message=message, history=lc_history),
        )
        print(response)
        if not response.intent:
            return IntentEnum.CHAT
        return response.intent
    except Exception as e:
        print(f"[classify_intent] 解析失败，回退为 CHAT: {e}")
        return IntentEnum.CHAT

async def fallback_chat(message: str, session_id: str, kb: KnowledgeBase, db: AsyncSession) -> dict:
    history = await load_session_history(session_id, db)
    lc_history = _to_langchain_messages(history)
    intent = await classify_intent(message, lc_history)
    if intent == "order":
        return { "reply": query_order(message), "intent": intent, "sources": [], "engine": "langchain"}
    if intent == "knowledge":
        answer, sources = await aanswer_with_rag(message, kb, get_llm(), lc_history)
        return { "reply": answer, "intent": intent, "sources": sources, "engine": "langchain"}
    chain = CHAT_PROMPT | get_llm()
    reply = await ainvoke_with_retry(chain.ainvoke, {"message": message, "history": lc_history})
    if hasattr(reply, "content"):
        reply = reply.content
    return {"reply": reply, "intent": "chat", "sources": [], "engine": "langchain"}


async def chat(message: str, session_id: str, db: AsyncSession) -> dict:
    entry = {"message": message[:80], "session_id": session_id, "status": 200}
    t_start = time.perf_counter()
    if not settings.AIROBOT_LLM_API_KEY:
        # traces.record({**entry, "intent": "no-key", "total_ms": 0.0})
        return {"reply": "未配置 AIROBOT_LLM_API_KEY，请复制 .env.example 为 .env 并填入密钥。",
                "intent": None, "sources": [], "engine": "langchain"}
    t_llm=time.perf_counter()
    kb = get_kb_instance(db)
    result = await fallback_chat(message, session_id,kb, db)
    entry.update(intent=result.get("intent"), engine=result.get("engine"),
                 llm_ms=round((time.perf_counter() - t_llm) * 1000, 1),
                 sources=len(result.get("sources", [])),
                 total_ms=round((time.perf_counter() - t_start) * 1000, 1))

    return result

def _run_crew_in_thread(message: str, history_text: str, kb: KnowledgeBase) -> dict:
    """在子线程跑 Crew，并注入 KB 供 search_knowledge 使用。"""
    bind_kb_for_crew(kb)
    try:
        return run_crew(message, history_text)
    finally:
        clear_kb_for_crew()


def _format_history_text(history: list[dict]) -> str:
    lines = []
    for m in history:
        role = "用户" if m["role"] == "user" else "助手"
        lines.append(f"{role}: {m['content']}")
    return "\n".join(lines)

def _maybe_cache(query_vec, result: dict, message: str) -> None:
    if query_vec is None:
        return
    if result.get("intent") == "order" or result.get("intent") == "alarm":
        return
    semantic_cache.put(query_vec,message, result)

async def run(
    message: str,
    session_id: str,
    kb: KnowledgeBase,
    db: AsyncSession,
    on_event=None,  # None=JSON；有回调=SSE
) -> dict:
    t_start = time.perf_counter()
    entry = {
        "message": message[:80],
        "session_id": session_id,
        "status": 200,
    }
    history = await load_session_history(session_id, db)
    query_vector = None
    is_alarm = is_alarm_message(message)
    if settings.cache_enabled and settings.AIROBOT_EMBEDDING_API_KEY and not history and not is_alarm:
        query_vector = await asyncio.to_thread(kb.embed_query, message)
        cached = semantic_cache.get(query_vector, message)
        if cached is not None:
            res = {**cached, "cache_hit": True}
            await save_turn(session_id, message, res["reply"], db)
            entry.update(cache_hit=True, intent=res.get("intent"),
                         cache_checked=True, total_ms=round((time.perf_counter() - t_start) * 1000, 1))
            traces.record(entry)
            return res
    # use_crew 且工具就绪时交给 Crew（走 investigate_alarm）；否则启发式直达 alarm
    _crew_ok = settings.use_crew and CREW_TOOLS_READY
    if is_alarm and not _crew_ok:
        res = await run_alarm_agent(message)
        await save_turn(session_id, message, res["reply"], db)
        entry.update(
            intent=res.get("intent", "alarm"),
            engine=res.get("engine", "alarm"),
            cache_hit=False,
            cache_checked=False,
            sources=len(res.get("sources") or []),
            total_ms=round((time.perf_counter() - t_start) * 1000, 1),
        )
        traces.record(entry)
        return res

    lc_history = _to_langchain_messages(history)
    if _crew_ok:
        try:
            history_text = _format_history_text(history)
            crew_result = await asyncio.to_thread(
                _run_crew_in_thread, message, history_text, kb
            )
            res = {
                "reply": crew_result["reply"],
                "intent": crew_result.get("intent", "crew"),
                "sources": crew_result.get("sources", []),
                "engine": "crew",
                "used_crew": True,
                "cache_hit": False,
            }
            _maybe_cache(query_vector, res, message)
            await save_turn(session_id, message, res["reply"], db)
            entry.update(
                intent=res.get("intent"),
                engine=res.get("engine"),
                cache_hit=False,
                cache_checked=query_vector is not None,
                sources=len(res.get("sources", [])),
                total_ms=round((time.perf_counter() - t_start) * 1000, 1),
            )
            traces.record(entry)
            return res
        except Exception as e:
            print(f"[run_crew] 解析失败，回退为 CHAT: {e}")
    intent = await classify_intent(message, lc_history)
    if on_event:
        on_event({"type": "stage", "name": intent})

    if intent == IntentEnum.ALARM or intent == "alarm":
        res = await run_alarm_agent(message)
    elif intent == "order":
        answer = query_order(message)
        res = {"reply": answer, "intent": intent, "sources": [], "engine": "langchain", "cache_hit": False}
    elif intent == "knowledge":
        answer, sources = await aanswer_with_rag(message, kb, get_llm(), lc_history)
        res = {"reply": answer, "intent": intent, "sources": sources, "engine": "langchain", "cache_hit": False}
    else:
        chain = CHAT_PROMPT | get_llm()
        reply = await ainvoke_with_retry(chain.ainvoke, {"message": message, "history": lc_history})
        if hasattr(reply, "content"):
            reply = reply.content
        res = {"reply": reply, "intent": "chat", "sources": [], "engine": "langchain", "cache_hit": False}
    if on_event:
        on_event(res)
    _maybe_cache(query_vector, res, message)
    await save_turn(session_id, message, res["reply"], db)
    entry.update(
        intent=res.get("intent"),
        engine=res.get("engine"),
        cache_hit=res.get("cache_hit", False),
        cache_checked=query_vector is not None,
        sources=len(res.get("sources", [])),
        total_ms=round((time.perf_counter() - t_start) * 1000, 1),
    )
    traces.record(entry)
    return res
async def run_astream(
    message: str,
    session_id: str,
    kb: KnowledgeBase,
    db: AsyncSession,
):
    t_start = time.perf_counter()
    history = await load_session_history(session_id, db)
    lc_history = _to_langchain_messages(history)
    query_vector = None

    yield {"type": "stage", "stage": "rate_limit", "msg": "限流检查通过", "ms": 0, "ok": True}
    is_alarm = is_alarm_message(message)
    if settings.cache_enabled and settings.AIROBOT_EMBEDDING_API_KEY and not history and not is_alarm:
        yield {"type": "stage", "stage": "cache", "msg": "语义缓存查询中…", "ms": 0}
        t_cache = time.perf_counter()
        query_vector = await asyncio.to_thread(kb.embed_query, message)
        cached = semantic_cache.get(query_vector, message)
        cache_ms = round((time.perf_counter() - t_cache) * 1000, 1)
        if cached is not None:
            yield {"type": "stage", "stage": "cache", "msg": "语义缓存命中", "ms": cache_ms, "ok": True, "hit": True}
            yield {"type": "intent", "intent": cached.get("intent", "chat")}
            yield {"type": "token", "content": cached.get("reply", "")}
            await save_turn(session_id, message, cached.get("reply", ""), db)
            total_ms = round((time.perf_counter() - t_start) * 1000, 1)
            traces.record({
                "message": message[:80], "session_id": session_id, "status": 200,
                "intent": cached.get("intent"), "engine": cached.get("engine", "langchain"),
                "cache_hit": True, "cache_checked": True, "cache_lookup_ms": cache_ms,
                "total_ms": total_ms,
            })
            yield {
                "type": "done",
                "reply": cached.get("reply", ""),
                "intent": cached.get("intent"),
                "sources": cached.get("sources", []),
                "engine": cached.get("engine", "langchain"),
                "cache_hit": True,
                "total_ms": total_ms,
            }
            return
        yield {"type": "stage", "stage": "cache", "msg": "语义缓存未命中", "ms": cache_ms, "ok": True, "hit": False}
    else:
        reason = "多轮会话" if history else "缓存未开启"
        yield {"type": "stage", "stage": "cache", "msg": f"跳过语义缓存（{reason}）", "ms": 0, "skipped": True}

    _crew_ok = settings.use_crew and CREW_TOOLS_READY
    if is_alarm and not _crew_ok:
        yield {"type": "intent", "intent": "alarm"}
        full_reply = ""
        sources: list = []
        meta = None
        async for ev in run_alarm_agent_stream(message):
            if ev.get("type") == "token" and ev.get("content"):
                full_reply += ev["content"]
                if ev.get("sources"):
                    sources = ev["sources"]
                yield ev
            elif ev.get("type") == "stage":
                meta = ev.get("meta") or meta
                yield ev
            elif ev.get("type") == "done":
                full_reply = ev.get("reply") or full_reply
                sources = ev.get("sources") or sources
                meta = ev.get("meta") or meta
        await save_turn(session_id, message, full_reply, db)
        total_ms = round((time.perf_counter() - t_start) * 1000, 1)
        traces.record({
            "message": message[:80], "session_id": session_id, "status": 200,
            "intent": "alarm", "engine": "alarm", "cache_hit": False,
            "cache_checked": False,
            "sources": len(sources), "total_ms": total_ms,
        })
        yield {
            "type": "done",
            "reply": full_reply,
            "intent": "alarm",
            "sources": sources,
            "engine": "alarm",
            "cache_hit": False,
            "meta": meta,
            "total_ms": total_ms,
        }
        return

    if _crew_ok:
        try:
            yield {"type": "stage", "stage": "crew", "msg": "Crew 多 Agent 处理中…", "ok": True}
            history_text = _format_history_text(history)
            crew_result = await asyncio.to_thread(
                _run_crew_in_thread, message, history_text, kb
            )
            reply = crew_result["reply"]
            intent = crew_result.get("intent", "crew")
            sources = crew_result.get("sources", [])
            yield {"type": "intent", "intent": intent}
            yield {"type": "token", "content": reply}
            res = {
                "reply": reply, "intent": intent, "sources": sources,
                "engine": "crew", "used_crew": True, "cache_hit": False,
            }
            _maybe_cache(query_vector, res, message)
            await save_turn(session_id, message, reply, db)
            total_ms = round((time.perf_counter() - t_start) * 1000, 1)
            traces.record({
                "message": message[:80], "session_id": session_id, "status": 200,
                "intent": intent, "engine": "crew", "cache_hit": False,
                "cache_checked": query_vector is not None,
                "sources": len(sources), "total_ms": total_ms,
            })
            yield {**res, "type": "done", "total_ms": total_ms}
            return
        except Exception as e:
            print(f"[run_astream crew] 降级 P3: {e}")
            yield {"type": "stage", "stage": "crew", "msg": f"Crew 失败，降级 langchain: {e}", "ok": False}

    t_intent = time.perf_counter()
    intent = await classify_intent(message, lc_history)
    intent_ms = round((time.perf_counter() - t_intent) * 1000, 1)
    yield {"type": "stage", "stage": "intent", "msg": f"意图识别为 {intent}", "ms": intent_ms, "ok": True}
    yield {"type": "intent", "intent": str(intent)}
    full_reply = ""
    sources = []
    engine = "langchain"
    if intent == IntentEnum.ALARM or intent == "alarm":
        engine = "alarm"
        yield {"type": "stage", "stage": "alarm", "msg": "意图识别为监控告警", "ok": True}
        async for ev in run_alarm_agent_stream(message):
            if ev.get("type") == "token" and ev.get("content"):
                full_reply += ev["content"]
                if ev.get("sources"):
                    sources = ev["sources"]
                yield ev
            elif ev.get("type") == "stage":
                yield ev
            elif ev.get("type") == "done":
                full_reply = ev.get("reply") or full_reply
                sources = ev.get("sources") or sources
    elif intent == "order":
        yield {"type": "stage", "stage": "tool", "msg": "调用 query_order", "ok": True}
        full_reply = query_order(message)
        yield {"type": "token", "content": full_reply}
    elif intent == "knowledge":
        yield {"type": "stage", "stage": "retrieval", "msg": "混合检索 + RAG 生成中…", "ok": True}
        async for event in aanswer_with_rag_stream(message, kb, get_llm(), lc_history):
            if event.get("sources"):
                sources = event["sources"]
            if event["type"] == "token" and event.get("content"):
                full_reply += event["content"]
            yield event
    else:
        yield {"type": "stage", "stage": "generate", "msg": "闲聊生成中…", "ok": True}
        chain = CHAT_PROMPT | get_llm()
        async for chunk in chain.astream({"message": message, "history": lc_history}):
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            if token:
                full_reply += token
                yield {"type": "token", "content": token}

    res = {
        "reply": full_reply,
        "intent": "alarm" if engine == "alarm" else str(intent),
        "sources": sources,
        "engine": engine,
        "cache_hit": False,
    }
    _maybe_cache(query_vector, res, message)
    await save_turn(session_id, message, full_reply, db)
    total_ms = round((time.perf_counter() - t_start) * 1000, 1)
    traces.record({
        "message": message[:80], "session_id": session_id, "status": 200,
        "intent": res["intent"], "engine": engine,
        "cache_hit": False, "cache_checked": query_vector is not None,
        "intent_ms": intent_ms, "sources": len(sources), "total_ms": total_ms,
    })
    yield {"type": "stage", "stage": "write", "msg": "写入会话记忆", "ok": True}
    yield {"type": "done", **res, "total_ms": total_ms}


if __name__ == "__main__":
    from app.database import get_db, init_db

    async def _test():
        await init_db()
        async for db in get_db():
            kb = get_kb_instance(db)
            all_sessions = await get_sessions(db)
            print("all_sessions::",all_sessions)
            res = await run("运费谁出", session_id="1", kb=kb, db=db)
            print(res)
            break

    asyncio.run(_test())
