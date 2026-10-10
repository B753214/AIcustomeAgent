"""Run 内模型 token 预算：从 LLM 响应提取用量，写入 BudgetPolicy。

仅在 Runtime ``tool_run_scope``（含 budget）内生效；无绑定时空操作。
"""
from __future__ import annotations

from typing import Any


def extract_token_count(result: Any) -> int:
    """从 LangChain 消息 / dict / usage 结构尽量解析 total tokens。"""
    if result is None:
        return 0
    if isinstance(result, bool):
        return 0
    if isinstance(result, (int, float)):
        return max(0, int(result))

    if isinstance(result, dict):
        for key in ("total_tokens", "totalTokens"):
            if result.get(key) is not None:
                return max(0, int(result[key]))
        inp = result.get("input_tokens") or result.get("prompt_tokens") or 0
        out = result.get("output_tokens") or result.get("completion_tokens") or 0
        if inp or out:
            return max(0, int(inp) + int(out))
        for nest_key in ("token_usage", "usage", "usage_metadata"):
            nested = result.get(nest_key)
            if isinstance(nested, dict) and nested and nested is not result:
                n = extract_token_count(nested)
                if n:
                    return n
        return 0

    usage_meta = getattr(result, "usage_metadata", None)
    if usage_meta is not None:
        n = extract_token_count(usage_meta)
        if n:
            return n

    resp_meta = getattr(result, "response_metadata", None)
    if isinstance(resp_meta, dict):
        n = extract_token_count(resp_meta)
        if n:
            return n

    # LLMResult / ChatResult
    llm_output = getattr(result, "llm_output", None)
    if isinstance(llm_output, dict):
        n = extract_token_count(llm_output)
        if n:
            return n

    return 0


def check_model_budget() -> None:
    """模型调用前检查累计 token / tool 是否已超预算。"""
    from app.harness.tools.binding import get_tool_run_binding

    binding = get_tool_run_binding()
    if binding is None or binding.budget is None:
        return
    binding.budget.check(binding.ctx)


def record_model_usage(result: Any) -> int:
    """模型调用后把本次 tokens 累加进 ctx.budget；返回记入数量。"""
    from app.harness.tools.binding import get_tool_run_binding

    tokens = extract_token_count(result)
    binding = get_tool_run_binding()
    if binding is None or binding.budget is None or tokens <= 0:
        return tokens

    binding.budget.increment(binding.ctx, tokens=tokens)
    usage = binding.ctx.metadata.setdefault("usage", {})
    usage["tokens_used"] = int(binding.ctx.budget.get("tokens_used", 0))
    usage["max_tokens"] = binding.ctx.budget.get("max_tokens")
    return tokens
