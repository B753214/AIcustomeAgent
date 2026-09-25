from __future__ import annotations

import re
from typing import Any

from app.harness.contracts import (
    HarnessError,
    HarnessErrorCategory,
    RunContext,
    RunEvent,
)


class DataPolicy:
    """敏感数据打码 & 断言无明文。

    打码覆盖三类出口：
    - ``RunRequest.input`` / ``RunContext.messages``：进 Run 前打码
    - ``RunEvent.payload``：事件持久化 / 下发前打码

    用法（组合进 PolicySet）::

        class ChatPolicySet(PolicySet):
            def __init__(self):
                self._data = DataPolicy()

            def apply_before(self, ctx):
                self._data.sanitize_ctx(ctx)   # 打码 input + messages
                return ctx

        # Runtime.execute_stream 里，ev.model_copy 之后、persist 之前：
        # self._data.sanitize_event(out)
        # self._data.assert_no_secrets(out.payload)
    """

    def __init__(self, patterns: dict[str, str] | None = None) -> None:
        """
        Args:
            patterns: 额外/覆盖的正则规则 ``{name: regex}``，
                      例如 ``{"email": r"\\b[\\w.+-]+@[\\w.-]+\\.[a-zA-Z]{2,}\\b"}``。
                      默认规则已覆盖 sk-*、password=、api_key=、token= 等。
        """
        default: dict[str, str] = {
            "sk_key": r"\bsk-[A-Za-z0-9_\-]{10,}\b",
            "password": r"(?i)\b(password|passwd|pwd)\s*[:=]\s*\S+",
            "api_key": r"(?i)\b(api[_-]?key|api[_-]?secret)\s*[:=]\s*\S+",
            "token": r"(?i)\b(access[_-]?token|auth[_-]?token|secret[_-]?key)\s*[:=]\s*\S+",
            "bearer": r"(?i)\bBearer\s+[A-Za-z0-9_\-.]{8,}",
            "private_key": r"-----BEGIN\s+(RSA|EC|OPENSSH|DSA)?\s*PRIVATE\s*KEY-----[\s\S]*?-----END\s+\1?\s*PRIVATE\s*KEY-----",
        }
        if patterns:
            default.update(patterns)
        self._patterns: list[tuple[str, re.Pattern[str]]] = [
            (name, re.compile(pat)) for name, pat in default.items()
        ]

    # ------------------------------------------------------------------
    # 核心：字符串打码
    # ------------------------------------------------------------------

    @staticmethod
    def _mask(s: str, *, keep_head: int = 2, keep_tail: int = 2) -> str:
        """把命中的敏感字符串替换成掩码 ``sk-****abcd``。"""
        if len(s) <= keep_head + keep_tail:
            return "*" * len(s)
        return s[:keep_head] + "*" * (len(s) - keep_head - keep_tail) + s[-keep_tail:]

    def mask_str(self, text: str) -> str:
        """对单个字符串应用所有规则打码。"""
        result = text
        for _name, regex in self._patterns:
            result = regex.sub(self._replace_match, result)
        return result

    def _replace_match(self, m: re.Match[str]) -> str:
        """re.sub 的回调：整个匹配替换成掩码。"""
        raw = m.group(0)
        return self._mask(raw)

    # ------------------------------------------------------------------
    # 递归容器打码（ctx / payload 都要走这个）
    # ------------------------------------------------------------------

    def sanitize(self, obj: Any) -> Any:
        """递归打码 dict / list / str；其它类型原样返回。

        - dict / list：**原地**修改，同时返回原对象（方便链式调用）。
        - str：返回打码后的新字符串。
        """
        if isinstance(obj, str):
            return self.mask_str(obj)
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                obj[k] = self.sanitize(v)
            return obj
        if isinstance(obj, list):
            for i, v in enumerate(obj):
                obj[i] = self.sanitize(v)
            return obj
        if isinstance(obj, tuple):
            return tuple(self.sanitize(v) for v in obj)
        return obj

    # ------------------------------------------------------------------
    # 具体 hook 方法
    # ------------------------------------------------------------------

    def sanitize_ctx(self, ctx: RunContext) -> None:
        """进 Run 前：打码 RunRequest.input 与 RunContext.messages。"""
        if ctx.request.input:
            ctx.request.input = self.mask_str(ctx.request.input)
        if ctx.messages:
            self.sanitize(ctx.messages)

    def sanitize_event(self, event: RunEvent) -> None:
        """事件持久化 / 下发前：打码 payload。"""
        if event.payload:
            self.sanitize(event.payload)

    # ------------------------------------------------------------------
    # 断言：输出无明文
    # ------------------------------------------------------------------

    def assert_no_secrets(self, obj: Any) -> None:
        """递归扫描 obj（通常是 RunEvent.payload），发现敏感明文残留就 raise。

        与 sanitize 配合使用：先 sanitize 一遍，再 assert_no_secrets 双重保险。
        典型场景：Executor 漏打码的异常 message、第三方 SDK 抛的原始 token。
        """
        findings: list[str] = []
        self._scan_for_secrets(obj, findings)
        if findings:
            raise HarnessError(
                HarnessErrorCategory.POLICY,
                f"输出含敏感明文未打码: {findings}",
                details={
                    "policy": "data",
                    "findings": findings[:10],
                    "total": len(findings),
                },
            )

    def _scan_for_secrets(self, obj: Any, findings: list[str]) -> None:
        if isinstance(obj, str):
            for name, regex in self._patterns:
                for m in regex.finditer(obj):
                    findings.append(f"{name}: {m.group(0)[:40]}")
        elif isinstance(obj, dict):
            for v in obj.values():
                self._scan_for_secrets(v, findings)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                self._scan_for_secrets(v, findings)