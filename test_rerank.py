import sys
sys.path.insert(0, r"D:\python\customeAgent\AICustomeRobort")
from app.config import settings
import dashscope

docs = [
    "七天无理由退换货政策：买家在签收后七天内可以申请无理由退换货。",
    "如何修改收货地址。",
    "商品质量问题处理。",
    "支付方式支持。",
    "卖家发货时间。",
]
query = "七天无理由退换货"

key = settings.AIROBOT_EMBEDDING_API_KEY

for model_name in ["qwen3-rerank", "gte-rerank", "gte-rerank-v2"]:
    print(f"=== Testing {model_name} ===")
    try:
        resp = dashscope.TextReRank.call(
            model=model_name,
            query=query,
            documents=docs,
            top_n=3,
            api_key=key,
        )
        print(f"status: {resp.status_code}")
        print(f"code: {getattr(resp, 'code', 'N/A')}")
        print(f"message: {getattr(resp, 'message', 'N/A')}")
        if resp.output and hasattr(resp.output, "results") and resp.output.results:
            for r in resp.output.results:
                print(f"  idx={r['index']} score={r['relevance_score']:.4f}")
    except Exception as e:
        print(f"error: {e}")
    print()