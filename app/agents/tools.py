import asyncio
import random
import re

from app.agents.alarm import run_alarm_agent
from app.agents.weather import query_weather
from app.rag.retriever import answer_with_rag

_TOOL_ERROR_PREFIX = "[TOOL_ERROR]"

_last_rag_sources: list[str] = []
def get_last_rag_sources() -> list[str]:
    return list(_last_rag_sources)
def clear_last_rag_sources() -> None:
    global _last_rag_sources
    _last_rag_sources = []

def query_order(message: str) -> str:
    """查询用户订单状态与物流信息（Mock 数据）。

    Args:
        message: 用户消息，可包含订单号（6 位以上数字）；无订单号时使用默认单号。
    """
    match = re.search(r"\d{6,}", message)
    order_no = match.group(0) if match else "202608090001"

    if random.random() < 0.6:
        return (
            f"{_TOOL_ERROR_PREFIX} 订单 {order_no} 查询失败："
            "订单服务暂时不可用，请稍后重试或联系客服。"
        )

    return (
        f"订单 {order_no}：状态=已发货，物流=顺丰速运 SF1234567890，"
        "预计 8 月 11 日送达。如需退款或售后，请在订单详情页申请。"
    )

def search_knowledge(query: str) -> str:
    """检索平台知识库并基于资料回答问题（RAG）。

    Args:
        query: 用户问题原文或提炼后的检索关键词。
    """
    global _last_rag_sources
    answer, sources  = answer_with_rag(query)
    print("RAG 源:", sources)
    _last_rag_sources = sources
    return answer

def after_sale_rule() -> str:
    """查询平台售后与退货规则。无需参数，直接调用即可。"""
    return ("售后规则：签收 7 天内可申请无理由退货（需不影响二次销售）；"
            "商品破损或与描述不符的，运费由卖家承担；请上传凭证由 AI 质检确认。")

def investigate_alarm(message: str) -> str:
    """排查监控告警 / info-plate 链接，输出 RCA（结论/证据/建议）。

    Args:
        message: 告警原文或含监控 URL 的用户消息。
    """
    try:
        res = asyncio.run(run_alarm_agent(message))
        return res.get("reply") or str(res)
    except Exception as e:
        return f"告警排查失败：{e}"
search_knowledge_tool = None
query_order_tool = None
after_sale_rule_tool = None
CREW_TOOLS_READY = False
investigate_alarm_tool = None
query_weather_tool = None
try:
    from crewai.tools import tool
    search_knowledge_tool = tool("search_knowledge")(search_knowledge)
    query_order_tool = tool("query_order")(query_order)
    after_sale_rule_tool = tool("after_sale_rule")(after_sale_rule)
    investigate_alarm_tool = tool("investigate_alarm")(investigate_alarm)
    query_weather_tool = tool("query_weather")(query_weather)
    CREW_TOOLS_READY = True
except ImportError:
    CREW_TOOLS_READY = False