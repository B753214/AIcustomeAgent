from __future__ import annotations

from app.harness.policies import DataPolicy
from app.harness.policies.auth import AuthPolicy
from app.harness.policies.base import PolicySet
from app.harness.policies.budget import BudgetPolicy
from app.harness.policies.timeout import TimeoutPolicy
from app.harness.policies.tool_policy import ToolPolicy


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
    """只登记通用策略：``default`` / ``strict``。

    各 Agent 的预算差异不要写在这里——在 ``AgentDefinition.budget`` 上配置，
    建 ``AgentRuntime(..., budget=defn.budget)`` 时覆盖。
    """
    reg = registry or PolicyRegistry()
    if "default" not in reg.list_names():
        reg.register(
            "default",
            PolicySet(
                auth=AuthPolicy(allowlist={"api", "internal", "cli"}),
                budget=BudgetPolicy(max_tool_calls=20, max_tokens=5000),
                timeout=TimeoutPolicy(
                    run_seconds=120,
                    model_seconds=60,
                    tool_seconds=30,
                ),
                data=DataPolicy(),
                tool=ToolPolicy(allowlist=None),
            ),
        )
    if "strict" not in reg.list_names():
        reg.register(
            "strict",
            PolicySet(
                auth=AuthPolicy(allowlist={"api"}),
                budget=BudgetPolicy(max_tool_calls=0),
                timeout=TimeoutPolicy(run_seconds=5, model_seconds=5, tool_seconds=5),
                data=DataPolicy(),
                tool=ToolPolicy(allowlist=set()),
            ),
        )
    return reg
