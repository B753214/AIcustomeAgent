from __future__ import annotations

from app.harness.contracts import HarnessError, HarnessErrorCategory


class RetryPolicy:
    """仅对瞬时错误建议重试；写操作且非幂等时不重试。

    should_retry(err, attempt, *, idempotent=True) -> bool
    """

    def __init__(self, max_attempts: int = 3) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = max_attempts
        self._retryable_categories = frozenset(
            {
                HarnessErrorCategory.TIMEOUT,
                HarnessErrorCategory.MODEL,  # 含网络抖动类模型失败时可由上层映射
            }
        )
        self._retryable_type_names = frozenset(
            {
                "TimeoutError",
                "asyncio.TimeoutError",
                "ConnectError",
                "ConnectTimeout",
                "ReadTimeout",
                "NetworkError",
            }
        )

    def should_retry(
        self,
        err: BaseException,
        attempt: int,
        *,
        idempotent: bool = True,
    ) -> bool:
        """attempt 从 1 起算（第 1 次失败后 attempt=1）。

        - 已达 max_attempts：False
        - 非幂等写操作：False
        - HarnessError：仅 TIMEOUT（及可选 MODEL）可重试
        - 其它：按异常类型名粗判网络/超时
        """
        if attempt >= self.max_attempts:
            return False
        if not idempotent:
            return False

        if isinstance(err, HarnessError):
            return err.category in self._retryable_categories

        name = type(err).__name__
        qual = f"{type(err).__module__}.{name}" if hasattr(type(err), "__module__") else name
        if name in self._retryable_type_names or qual in self._retryable_type_names:
            return True
        # 常见 httpx / aiohttp 命名
        if "Timeout" in name or "Connect" in name:
            return True
        return False
