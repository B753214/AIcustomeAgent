"""稳定性工具：tenacity 指数退避重试（429 / 5xx / 网络错误自动重试）。"""
import logging
from typing import Any, Callable

import httpx
import openai
from tenacity import (
    AsyncRetrying,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)
from tenacity.before_sleep import before_sleep_log

from app.config import settings

logger = logging.getLogger("airobot.resilience")


def _is_retryable(exc: BaseException) -> bool:
    """可重试：限流 429、5xx、网络/超时；校验/鉴权类错误不重试。"""
    if isinstance(
        exc,
        (
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.InternalServerError,
        ),
    ):
        return True
    if isinstance(exc, openai.APIStatusError):
        # 429 限流、5xx 服务端错误可重试；4xx 业务/鉴权错误不重试
        return exc.status_code == 429 or exc.status_code >= 500
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            TimeoutError,
            ConnectionError,
        ),
    ):
        return True
    return False


def _sync_retry_kwargs() -> dict:
    return {
        "stop": stop_after_attempt(settings.retry_attempts),
        "wait": wait_random_exponential(multiplier=0.5, max=settings.retry_max_wait),
        "retry": retry_if_exception(_is_retryable),
        "before_sleep": before_sleep_log(logger, logging.WARNING),
        "reraise": True,
    }


def invoke_with_retry(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """同步调用：Embedding 等外部依赖，失败自动指数退避重试。"""

    @retry(**_sync_retry_kwargs())
    def _call() -> Any:
        return fn(*args, **kwargs)

    return _call()


async def ainvoke_with_retry(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """异步调用版（ainvoke 等）。"""
    async for attempt in AsyncRetrying(**_sync_retry_kwargs()):
        with attempt:
            return await fn(*args, **kwargs)
    raise RuntimeError("unreachable")  # pragma: no cover


def safe_call(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """调用失败仅告警不抛出（用于非关键路径，如统计/缓存写入）。"""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("非关键路径调用失败: %s", exc)
        return None
