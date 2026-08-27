from pydantic import BaseModel, Field

from app.agents.tools import clear_last_rag_sources, get_last_rag_sources
from app.config import settings
from app.rag.retriever import bind_kb_for_crew, clear_kb_for_crew, get_kb_instance


def run_crew(message: str, history_text: str=""):
    from crewai import Agent, Crew, LLM, Process, Task
    clear_last_rag_sources()
    from app.agents.tools import (
        search_knowledge_tool,
        query_order_tool,
        after_sale_rule_tool,
    )

    class IntentResult(BaseModel):
        intent: str = Field(description="可选值 knowledge | order | chat")
        confidence: float = Field(description="0~1置信分数")
        reason: str = Field(description="简单说明判断依据")

    llm= LLM(
        model=f"dashscope/{settings.AIROBOT_LLM_MODEL}",
        base_url=settings.AIROBOT_LLM_BASE_URL,
        api_key=settings.AIROBOT_LLM_API_KEY,
        temperature=0.7,
    )

    history_desc=f"\n对话历史:\n{history_text}" if history_text else ""


    router = Agent(
        role="意图识别官",
        goal="准确判断用户消息的意图类型",
        backstory=("你是二手交易平台的意图识别专家，"
                   "只输出 JSON：{{'intent': 'knowledge|order|chat', 'reason': '简短理由'}}"),
        llm=llm,
        verbose=False,
    )

    executive = Agent(
        role="客服执行员",
        goal="根据意图调用对应工具，给出真实、友好、简洁的中文答复",
        backstory=("你是二手交易平台客服，擅长用工具查订单、查知识库、讲售后规则。"
                   "必须依据工具返回的真实数据作答，禁止编造。"),
        tools=[query_order_tool, after_sale_rule_tool, search_knowledge_tool],
        llm=llm,
        verbose=False,
    )

    task_router = Task(
        description=f"分析用户消息：{message}（如有对话历史请结合上下文）{history_desc}。只输出意图 JSON。",
        output_pydantic=IntentResult,
        agent=router,
        expected_output="结构化意图 JSON",
    )

    task_exec = Task(
        description=(
            "根据意图识别官的结论处理用户消息。规则："
            "intent=knowledge 时调用 search_knowledge 回答；"
            "intent=order 时调用 query_order 查询订单；"
            "涉及售后/退货时调用 after_sale_rule；"
            "intent=chat 时直接礼貌闲聊；"
            "结合对话历史保持上下文连贯。"
            "最终给出面向用户的完整中文答复。"
            f"会话历史：{history_desc}"
        ),
        expected_output="给用户的最终中文答复",
        agent=executive,
    )
    crew = Crew(
        agents=[router, executive],
        tasks=[task_router, task_exec],
        process=Process.sequential,
        verbose=False,
    )
    result = crew.kickoff()
    from rich import print as rprint
    intent = "crew"
    rprint("CrewAI 结果:", result)
    # rprint("任务输出:", result.tasks_output[0])
    if hasattr(result, "tasks_output") and result.tasks_output:
        first = result.tasks_output[0]
        if hasattr(first, "pydantic") and first.pydantic:
            intent = first.pydantic.intent
    return {
        "reply": str(getattr(result, "raw", result)),
        "sources": get_last_rag_sources(),
        "intent": intent,
           }

if __name__ == "__main__":
    import asyncio
    from app.database import get_db, init_db

    async def _init_kb():
        await init_db()
        async for db in get_db():
            kb = get_kb_instance(db)
            await kb.build_index()
            return kb
        return None

    async def _main():
        kb = await _init_kb()
        if kb is None:
            raise RuntimeError("KnowledgeBase 初始化失败")
        bind_kb_for_crew(kb)
        try:
            print(run_crew("七天无理由退货怎么申请"))
        finally:
            clear_kb_for_crew()

    asyncio.run(_main())
