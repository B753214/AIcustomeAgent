import re
import asyncio

from app.rag.retriever import aanswer_with_rag, get_cached_kb


def query_order(message: str) -> str:
    """查询用户订单状态与物流信息（Mock 数据）。"""
    match = re.search(r"\d{6,}", message)
    order_no = match.group(0) if match else "202608090001"
    return (
        f"订单 {order_no}：状态=已发货，物流=顺丰速运 SF1234567890，"
        "预计 8 月 11 日送达。如需退款或售后，请在订单详情页申请。"
    )

def search_knowledge(query: str) -> str:
    """检索平台知识库并基于资料回答问题（RAG）。"""
    kb = get_cached_kb()
    if kb is None:
        return "知识库尚未初始化完成，请稍后再试。"
    answer, _ = asyncio.run(aanswer_with_rag(query, kb))
    return answer

def after_sale_rule(_message: str) -> str:
    """查询平台售后与退货规则。"""
    return ("售后规则：签收 7 天内可申请无理由退货（需不影响二次销售）；"
            "商品破损或与描述不符的，运费由卖家承担；请上传凭证由 AI 质检确认。")

