from __future__ import annotations

from app.harness.policies.base import PolicySet


class PolicyRegistry:
    """按名登记/取出 PolicySet（先内存，不落库）。"""

    def __init__(self) -> None:
        self._policies: dict[str, PolicySet] = {}

    def register(self, name: str, policy_set: PolicySet) -> None:
        if name in self._policies:
            raise ValueError(f"policy set {name!r} already registered")
        self._policies[name] = policy_set

    def get(self, name: str) -> PolicySet:
        if name not in self._policies:
            raise ValueError(f"policy set {name!r} not registered")
        return self._policies[name]

    def list_names(self) -> list[str]:
        return list(self._policies.keys())


def register_default_policies(registry: PolicyRegistry | None = None) -> PolicyRegistry:
    """登记空策略集 ``default``（与 AgentDefinition.policy_set 默认值对齐）。

    需要其它名字（如 chat_default）时请自行 register，避免挂两份同空壳。
    """
    reg = registry or PolicyRegistry()
    if "default" not in reg.list_names():
        reg.register("default", PolicySet())
    return reg
