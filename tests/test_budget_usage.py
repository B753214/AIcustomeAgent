"""模型 token 预算：提取用量 + 绑定内 check/record。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from app.harness.contracts import (
    HarnessError,
    HarnessErrorCategory,
    RunContext,
    RunRequest,
)
from app.harness.policies import BudgetPolicy, check_model_budget, extract_token_count
from app.harness.policies.budget_usage import record_model_usage
from app.harness.registry import ToolRegistry
from app.harness.runtime.cancellation import CancellationToken
from app.harness.tools import ToolRunner, tool_run_scope


def test_extract_from_usage_metadata():
    msg = AIMessage(
        content="hi",
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )
    assert extract_token_count(msg) == 15


def test_extract_from_response_metadata_token_usage():
    msg = AIMessage(
        content="hi",
        response_metadata={"token_usage": {"prompt_tokens": 3, "completion_tokens": 2}},
    )
    assert extract_token_count(msg) == 5


def test_extract_zero_when_unknown():
    assert extract_token_count(AIMessage(content="x")) == 0
    assert extract_token_count(SimpleNamespace(foo=1)) == 0
    assert extract_token_count({}) == 0


def test_check_and_record_under_binding():
    ctx = RunContext(
        run_id="r1",
        request=RunRequest(input="hi", caller="api"),
        cancellation_token=CancellationToken(),
    )
    budget = BudgetPolicy(max_tool_calls=10, max_tokens=20)
    budget.ensure_budget(ctx)

    with tool_run_scope(ctx, ToolRunner(ToolRegistry()), budget=budget):
        check_model_budget()
        n = record_model_usage(
            AIMessage(
                content="ok",
                usage_metadata={
                    "input_tokens": 8,
                    "output_tokens": 4,
                    "total_tokens": 12,
                },
            )
        )
        assert n == 12
        assert ctx.budget["tokens_used"] == 12
        check_model_budget()
        record_model_usage({"total_tokens": 8})
        assert ctx.budget["tokens_used"] == 20
        with pytest.raises(HarnessError) as ei:
            check_model_budget()
        assert ei.value.category is HarnessErrorCategory.POLICY
        assert ei.value.details["dimension"] == "tokens"


def test_no_binding_is_noop():
    check_model_budget()
    assert (
        record_model_usage(
            AIMessage(
                content="x",
                usage_metadata={
                    "input_tokens": 5,
                    "output_tokens": 4,
                    "total_tokens": 9,
                },
            )
        )
        == 9
    )
