import re


def query_order(message: str) -> str:
    """查询用户订单状态与物流信息（Mock 数据）。"""
    match = re.search(r"\d{6,}", message)
    order_no = match.group(0) if match else "202608090001"
    return (
        f"订单 {order_no}：状态=已发货，物流=顺丰速运 SF1234567890，"
        "预计 8 月 11 日送达。如需退款或售后，请在订单详情页申请。"
    )
