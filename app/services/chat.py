import asyncio
import time
from enum import StrEnum

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from pydantic import Field, BaseModel

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

_llm_cache: dict = {}
class IntentEnum(StrEnum):
    KNOWLEDGE = "knowledge"  # 知识问答
    ORDER = "order"          # 订单查询
    CHAT = "chat"            # 闲聊
    UNKNOWN = "unknown"      # 未知意图

INTENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "你是意图分类器，只输出 JSON：{{\"intent\": \"knowledge|order|chat|unknown\", \"confidence\": 0.7, \"reason\": \"简短理由\"}}"),
    MessagesPlaceholder("history"),
    ("human", "{message}"),
])

CHAT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是二手交易平台智能客服，语气友好简洁…"),
    MessagesPlaceholder("history"),
    ("human", "{message}"),
])

class Classifier(BaseModel):
    intent: IntentEnum = Field(IntentEnum.KNOWLEDGE, description="意图分类，可选值：knowledge（知识问答）/order（订单查询）/chat（闲聊）/unknown（未知）")
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
    if result.get("intent") == "order":
        return
    semantic_cache.put(query_vec,message, result)

async def run(
    message: str,
    session_id: str,
    kb: KnowledgeBase,
    db: AsyncSession,
    on_event=None,  # None=JSON；有回调=SSE
) -> dict:
    history = await load_session_history(session_id, db)
    query_vector = None
    if settings.cache_enabled and settings.AIROBOT_EMBEDDING_API_KEY and not history:
        query_vector = await asyncio.to_thread(kb.embed_query, message)
        cached = semantic_cache.get(query_vector, message)
        if cached is not None:
            res = {**cached, "cache_hit": True}
            await save_turn(session_id, message, res["reply"], db)
            return res

    lc_history = _to_langchain_messages(history)
    if settings.USE_CREW and CREW_TOOLS_READY:
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
            return res
        except Exception as e:
            print(f"[run_crew] 解析失败，回退为 CHAT: {e}")

    intent = await classify_intent(message, lc_history)
    if on_event:
        on_event({"type": "stage", "name": intent})

    if intent == "order":
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
    return res
async def run_astream(
    message: str,
    session_id: str,
    kb: KnowledgeBase,
    db: AsyncSession,
):
    history = await load_session_history(session_id, db)
    lc_history = _to_langchain_messages(history)
    if settings.USE_CREW and CREW_TOOLS_READY:
        try:
            yield {"type": "stage", "stage": "crew", "msg": "Crew 多 Agent 处理中…"}
            history_text = _format_history_text(history)
            crew_result = await asyncio.to_thread(
                _run_crew_in_thread, message, history_text, kb
            )
            reply = crew_result["reply"]
            intent = crew_result.get("intent", "crew")
            sources = crew_result.get("sources", [])
            yield {"type": "intent", "intent": intent}
            # Crew 无原生 stream：整段输出（最简单）
            yield {"type": "token", "content": reply}
            # 可选：伪流式，体验更像打字机（按 20 字一块）
            # import re
            # for chunk in re.findall(r".{1,20}", reply, flags=re.S):
            #     yield {"type": "token", "content": chunk}
            await save_turn(session_id, message, reply, db)
            yield {
                "type": "done",
                "reply": reply,
                "intent": intent,
                "sources": sources,
                "engine": "crew",
                "used_crew": True,
            }
            return
        except Exception as e:
            print(f"[run_astream crew] 降级 P3: {e}")
            yield {"type": "stage", "stage": "crew", "msg": f"Crew 失败，降级 langchain: {e}"}

    intent = await classify_intent(message, lc_history)
    yield {"type": "stage", "stage": "intent", "msg": f"意图={intent}"}
    yield {"type": "intent", "intent": str(intent)}
    full_reply = ""
    sources = []
    if intent == "order":
        full_reply = query_order(message)
        yield {"type": "token","reply": full_reply, "intent": intent, "sources": [], "engine": "langchain"}
    elif intent == "knowledge":
        async for event in aanswer_with_rag_stream(message, kb, get_llm(), lc_history):
            if event["type"] == "token"and event.get("content"):
                full_reply+=event["content"]
            yield event
    else:
        chain = CHAT_PROMPT | get_llm()
        async for chunk in chain.astream({"message": message, "history": lc_history}):
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            if token:
                full_reply += token
                yield {"type": "token", "content": token}
    await save_turn(session_id, message, full_reply, db)
    yield {"type": "done", "reply": full_reply, "intent": intent, "sources": sources, "engine": "langchain"}


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
