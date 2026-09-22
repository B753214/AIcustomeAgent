from __future__ import annotations

from enum import StrEnum
from typing import Any


class HarnessErrorCategory(StrEnum):
    """Harness 错误分类（写入 RunResult.error / tool.failed payload）。"""

    VALIDATION = "validation"  # 入参校验失败
    MODEL = "model"  # LLM 调用失败
    TOOL = "tool"  # 工具执行失败
    POLICY = "policy"  # 权限 / 预算 / 限流
    TIMEOUT = "timeout"  # Run 或工具超时
    STORAGE = "storage"  # PG / Milvus / 文件 IO
    INTERNAL = "internal"  # 未归类兜底


class HarnessError(Exception):
    """统一异常。

    用法：
        raise HarnessError(HarnessErrorCategory.VALIDATION, "input 不能为空")
        raise HarnessError(
            HarnessErrorCategory.TOOL,
            "search 超时",
            details={"tool": "search_knowledge", "timeout_sec": 30},
        )

    序列化（给 RunResult.error 用）：
        RunResult(status="failed", error=err.to_dict())

    from_exception：可选便利方法，H2/ToolRunner 捕获底层异常时用来包装；
    H1 契约不强制依赖，可保留。
    """

    def __init__(
        self,
        category: HarnessErrorCategory,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "message": self.message,
            "details": self.details,
        }

    @classmethod
    def from_exception(
        cls,
        exc: BaseException,
        *,
        category: HarnessErrorCategory = HarnessErrorCategory.INTERNAL,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> HarnessError:
        """把任意底层异常包装成 HarnessError（可选便利方法）。"""
        if isinstance(exc, HarnessError):
            return exc
        merged = {
            "original_type": type(exc).__name__,
            "original_msg": str(exc),
            **(details or {}),
        }
        return cls(
            category=category,
            message=message or f"{type(exc).__name__}: {exc}",
            details=merged,
        )

    def __repr__(self) -> str:
        return (
            f"HarnessError(category={self.category.value!r}, "
            f"message={self.message!r})"
        )
