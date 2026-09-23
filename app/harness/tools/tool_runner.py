from __future__ import annotations

import asyncio
import inspect
from typing import Any

from app.harness.contracts import (
    HarnessError,
    HarnessErrorCategory,
    RunContext,
)
from app.harness.registry import ToolRegistry

_MAX_RESULT_CHARS = 8000


class ToolRunner:
    """按 Spec 执行工具：权限、校验、超时、截断、类型化错误。

    不负责打 tool.* 事件（留给 Executor）。
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def arun(
        self,
        name: str,
        arguments: dict[str, Any],
        ctx: RunContext,
        allowlist: list[str] | None = None,
    ) -> Any:
        try:
            spec, handler = self.registry.get(name)
        except ValueError as e:
            raise HarnessError(
                HarnessErrorCategory.VALIDATION,
                str(e),
                details={"tool": name},
            ) from e

        if allowlist is not None and name not in allowlist:
            raise HarnessError(
                HarnessErrorCategory.POLICY,
                f"tool {name!r} is not allowed in this context",
                details={"tool": name, "allowlist": list(allowlist)},
            )

        token = getattr(ctx, "cancellation_token", None)
        if token is not None and token.is_cancelled():
            raise HarnessError(
                HarnessErrorCategory.POLICY,
                f"tool {name!r} cancelled",
                details={"tool": name, "cancelled": True},
            )

        required = list((spec.input_schema or {}).get("required") or [])
        missing = [k for k in required if k not in arguments]
        if missing:
            raise HarnessError(
                HarnessErrorCategory.VALIDATION,
                f"tool {name!r} missing required arguments: {missing}",
                details={"tool": name, "missing": missing},
            )

        try:
            if inspect.iscoroutinefunction(handler):
                result = await asyncio.wait_for(
                    handler(**arguments),
                    timeout=spec.timeout_sec,
                )
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(handler, **arguments),
                    timeout=spec.timeout_sec,
                )
        except asyncio.TimeoutError as e:
            raise HarnessError(
                HarnessErrorCategory.TIMEOUT,
                f"tool {name!r} timed out after {spec.timeout_sec}s",
                details={"tool": name, "timeout_sec": spec.timeout_sec},
            ) from e
        except HarnessError:
            raise
        except Exception as e:
            raise HarnessError.from_exception(
                e,
                category=HarnessErrorCategory.TOOL,
                details={"tool": name},
            ) from e

        if isinstance(result, str):
            if len(result) > _MAX_RESULT_CHARS:
                result = result[:_MAX_RESULT_CHARS]
            if result.startswith("[TOOL_ERROR]"):
                raise HarnessError(
                    HarnessErrorCategory.TOOL,
                    result,
                    details={"tool": name},
                )

        return result
