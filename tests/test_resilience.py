"""P5-1 重试策略单元测试。"""
import pytest
import openai
import httpx

from app.services.resilience import _is_retryable, ainvoke_with_retry


@pytest.mark.parametrize(
    "exc,expected",
    [
        (openai.RateLimitError("429", response=httpx.Response(429, request=httpx.Request("POST", "http://x")), body=None), True),
        (openai.APIConnectionError(request=httpx.Request("POST", "http://x")), True),
        (openai.APITimeoutError(request=httpx.Request("POST", "http://x")), True),
        (openai.InternalServerError("500", response=httpx.Response(500, request=httpx.Request("POST", "http://x")), body=None), True),
        (openai.AuthenticationError("401", response=httpx.Response(401, request=httpx.Request("POST", "http://x")), body=None), False),
        (ValueError("bad json"), False),
        (ConnectionError("reset"), True),
    ],
)
def test_is_retryable(exc, expected):
    assert _is_retryable(exc) is expected


@pytest.mark.asyncio
async def test_ainvoke_retries_then_raises():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        raise openai.RateLimitError(
            "429",
            response=httpx.Response(429, request=httpx.Request("POST", "http://x")),
            body=None,
        )

    with pytest.raises(openai.RateLimitError):
        await ainvoke_with_retry(flaky)
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_ainvoke_no_retry_on_auth_error():
    calls = {"n": 0}

    async def bad_key():
        calls["n"] += 1
        raise openai.AuthenticationError(
            "401",
            response=httpx.Response(401, request=httpx.Request("POST", "http://x")),
            body=None,
        )

    with pytest.raises(openai.AuthenticationError):
        await ainvoke_with_retry(bad_key)
    assert calls["n"] == 1
