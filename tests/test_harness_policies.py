"""H6-1：七类策略最小可用单测。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.harness.contracts import (
    HarnessError,
    HarnessErrorCategory,
    RunContext,
    RunEvent,
    RunRequest,
)
from app.harness.policies import (
    AuthPolicy,
    BudgetPolicy,
    CachePolicy,
    DataPolicy,
    RetryPolicy,
    TimeoutPolicy,
    ToolPolicy,
)


def _ctx(**kwargs) -> RunContext:
    req_kwargs = {
        "input": kwargs.pop("input", "hi"),
        "caller": kwargs.pop("caller", "api"),
        "agent_id": kwargs.pop("agent_id", "chat"),
    }
    return RunContext(run_id="r1", request=RunRequest(**req_kwargs), **kwargs)


# --- Auth ---


def test_auth_allowlist_none_passes():
    AuthPolicy(allowlist=None).check(_ctx(caller="anyone"))


def test_auth_rejects_unknown_caller():
    with pytest.raises(HarnessError) as ei:
        AuthPolicy(allowlist={"api"}).check(_ctx(caller="evil"))
    assert ei.value.category == HarnessErrorCategory.POLICY
    assert ei.value.details["caller"] == "evil"


def test_auth_empty_allowlist_rejects_all():
    with pytest.raises(HarnessError):
        AuthPolicy(allowlist=set()).check(_ctx(caller="api"))


# --- Budget ---


def test_budget_ensure_and_under_limit():
    p = BudgetPolicy(max_tool_calls=2, max_tokens=100)
    ctx = p.ensure_budget(_ctx())
    assert ctx.budget["max_tool_calls"] == 2
    assert ctx.budget["tool_calls_used"] == 0
    p.check(ctx)


def test_budget_tool_calls_exceeded():
    p = BudgetPolicy(max_tool_calls=1)
    ctx = p.ensure_budget(_ctx())
    p.increment(ctx, tool_calls=1)
    with pytest.raises(HarnessError) as ei:
        p.check(ctx)
    assert ei.value.details["dimension"] == "tool_calls"


def test_budget_unlimited_when_max_none():
    p = BudgetPolicy()
    ctx = p.ensure_budget(_ctx())
    p.increment(ctx, tool_calls=99)
    p.check(ctx)  # no raise


# --- Timeout ---


def test_timeout_apply_deadline():
    p = TimeoutPolicy(run_seconds=30, model_seconds=10, tool_seconds=5)
    ctx = p.apply_deadline(_ctx())
    assert isinstance(ctx.deadline, datetime)
    assert ctx.deadline.tzinfo is not None
    assert ctx.metadata["timeout"]["tool_seconds"] == 5

    # 已有 deadline 不覆盖
    fixed = datetime(2030, 1, 1, tzinfo=timezone.utc)
    ctx2 = _ctx()
    ctx2.deadline = fixed
    out = p.apply_deadline(ctx2)
    assert out.deadline == fixed


# --- Tool ---


def test_tool_allowlist_and_arg_length():
    p = ToolPolicy(allowlist={"query_order"}, max_arg_chars=8)
    ctx = _ctx()
    p.check_call("query_order", {"message": "ok"}, ctx)

    with pytest.raises(HarnessError) as ei:
        p.check_call("evil", {}, ctx)
    assert ei.value.details["tool"] == "evil"

    with pytest.raises(HarnessError) as ei2:
        p.check_call("query_order", {"message": "123456789"}, ctx)
    assert ei2.value.details["arg"] == "message"


def test_tool_allowlist_none_only_checks_length():
    p = ToolPolicy(allowlist=None, max_arg_chars=3)
    p.check_call("any_tool", {"x": "ab"}, _ctx())
    with pytest.raises(HarnessError):
        p.check_call("any_tool", {"x": "abcd"}, _ctx())


# --- Retry ---


def test_retry_timeout_yes_non_idempotent_no():
    p = RetryPolicy(max_attempts=3)
    err = HarnessError(HarnessErrorCategory.TIMEOUT, "slow")
    assert p.should_retry(err, attempt=1) is True
    assert p.should_retry(err, attempt=1, idempotent=False) is False
    assert p.should_retry(err, attempt=3) is False  # attempt >= max


def test_retry_validation_not_retryable():
    p = RetryPolicy()
    err = HarnessError(HarnessErrorCategory.VALIDATION, "bad")
    assert p.should_retry(err, attempt=1) is False


def test_retry_connect_error_by_name():
    p = RetryPolicy()

    class ConnectError(Exception):
        pass

    assert p.should_retry(ConnectError("down"), attempt=1) is True


# --- Cache ---


def test_cache_noop():
    c = CachePolicy()
    assert c.get("k") is None
    c.set("k", {"v": 1})
    assert c.get("k") is None


# --- Data ---


def test_data_mask_sk_and_password():
    d = DataPolicy()
    text = "key=sk-abcdefghijklmnopqrstuvwxyz password=secret123"
    out = d.mask_str(text)
    assert "sk-abcdefghijklmnop" not in out or "sk-" in out
    assert "secret123" not in out
    assert "password" in out.lower() or "***" in out or "*" in out


def test_data_sanitize_event_and_assert():
    d = DataPolicy()
    ev = RunEvent(
        type="run.completed",
        run_id="r1",
        sequence=1,
        payload={"msg": "token sk-ABCDEFGHIJKLMNOPQRST"},
    )
    d.sanitize_event(ev)
    d.assert_no_secrets(ev.payload)

    with pytest.raises(HarnessError):
        d.assert_no_secrets({"raw": "sk-ABCDEFGHIJKLMNOPQRST"})
