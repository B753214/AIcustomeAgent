import asyncio
from datetime import time
from enum import StrEnum

from langchain.chat_models import init_chat_model
from langchain_classic.chains.qa_generation.prompt import CHAT_PROMPT
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import Field, BaseModel

from app.agents.tools import query_order
from app.config import settings
from app.rag.retriever import aanswer_with_rag
from app.services.resilience import ainvoke_with_retry
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.session_service import load_session_history, save_message, clear_session_history

_llm_cache: dict = {}
class IntentEnum(StrEnum):
    KNOWLEDGE = "knowledge"  # 知识问答
    ORDER = "order"          # 订单查询
    CHAT = "chat"            # 闲聊
    UNKNOWN = "unknown"      # 未知意图

INTENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "你是意图分类器，只输出 JSON：{{\"intent\": \"knowledge|order|chat\", \"reason\": \"简短理由\"}}"),
    ("human", "{message}"),
])

class Classifier(BaseModel):
    intent: IntentEnum = Field(IntentEnum.KNOWLEDGE, description="意图分类，可选值：knowledge（知识问答）/order（订单查询）/chat（闲聊）/unknown（未知）")
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

async def classify_intent(message: str) -> Classifier:
    llm_struct = get_llm().with_structured_output(Classifier)
    response = await llm_struct.ainvoke(INTENT_PROMPT.format(message=message))
    return response.intent | "chat"

async def fallback_chat(message: str, session_id: str, db: AsyncSession) -> dict:
    history = await load_session_history(session_id, db)
    intent = await classify_intent(message)
    if intent == "order":
        return { "reply": query_order(message), "intent": intent, "sources": [], "engine": "langchain"}
    if intent == "knowledge":
        answer, sources = await aanswer_with_rag(message, get_llm(), history)
        return { "reply": answer, "intent": intent, "sources": sources, "engine": "langchain"}
    chain = CHAT_PROMPT | get_llm()
    reply = await ainvoke_with_retry(chain.ainvoke, {"message": message, "history": history})
    return {"reply": reply, "intent": "chat", "sources": [], "engine": "langchain"}


async def chat(message: str, session_id: str) -> dict:
    entry = {"message": message[:80], "session_id": session_id, "status": 200}
    t_start = time.perf_counter()
    if not settings.llm_api_key:
        # traces.record({**entry, "intent": "no-key", "total_ms": 0.0})
        return {"reply": "未配置 AIROBOT_LLM_API_KEY，请复制 .env.example 为 .env 并填入密钥。",
                "intent": None, "sources": [], "engine": "langchain"}
    t_llm=time.perf_counter()
    result = await fallback_chat(message, session_id)
    entry.update(intent=result.get("intent"), engine=result.get("engine"),
                 llm_ms=round((time.perf_counter() - t_llm) * 1000, 1),
                 sources=len(result.get("sources", [])),
                 total_ms=round((time.perf_counter() - t_start) * 1000, 1))

    return result

if __name__ == "__main__":
    pass
