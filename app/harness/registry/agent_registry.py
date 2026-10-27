from __future__ import annotations

from dataclasses import dataclass, field

from app.harness.contracts import AgentExecutor
from app.harness.policies.budget import BudgetPolicy


@dataclass
class AgentDefinition:
    id: str
    executor: AgentExecutor  # Protocol，任意实现 astream 的对象
    version: str = "1.0"
    prompt_version: str = "1.0"
    tool_allowlist: list[str] = field(default_factory=list)
    model_roles: dict[str, str] = field(default_factory=dict)
    # 通用策略名（auth/timeout/data）；预算用 budget 字段在建 Runtime 时传入覆盖
    policy_set: str = "default"
    budget: BudgetPolicy | None = None


class AgentRegistry:
    def __init__(self) -> None:
        self._registry: dict[str, AgentDefinition] = {}

    def register(self, agent_id: str, defn: AgentDefinition) -> None:
        if agent_id != defn.id:
            raise ValueError(
                f"agent_id {agent_id!r} does not match definition.id {defn.id!r}"
            )
        if agent_id in self._registry:
            raise ValueError(f"Agent {agent_id} already registered")
        self._registry[agent_id] = defn

    def get(self, agent_id: str) -> AgentDefinition:
        if agent_id not in self._registry:
            raise ValueError(f"Agent {agent_id} not found")
        return self._registry[agent_id]

    def list_ids(self) -> list[str]:
        return list(self._registry.keys())


def register_builtin_agents(registry: AgentRegistry) -> AgentRegistry:
    """登记 chat / knowledge / alarm / echo。

    故意不注册 Crew：H4-5 决策为不下沉 Harness；Crew 仅旧 run 可选遗留。
    echo：H7-3 玩具 Agent，证明只 register 即可扩展。

    各 Agent 预算（建 Runtime 时 ``budget=defn.budget`` 覆盖 default）：
    - chat 20/8000：ReAct 多轮工具；对话+观察吃 token
    - knowledge None/RAG_RUN_TOKEN_BUDGET：默认16000，包含历史、资料及生成消耗
      （勿用 max_tool_calls=0：apply_before 时 0>=0 会直接拒跑）
    - alarm None/6000：同上，流水线多次 LLM，告警上下文更长
    - echo None/500：玩具，收紧 token
    """
    from app.agents.harness_alarm.executor import AlarmExecutor
    from app.agents.harness_chat.executor import ChatExecutor
    from app.agents.harness_echo.executor import EchoExecutor
    from app.agents.harness_knowledge.executor import KnowledgeExecutor
    from app.config import settings

    registry.register(
        "chat",
        AgentDefinition(
            id="chat",
            executor=ChatExecutor(),
            # maps_*：显式允许高德 MCP；未写前缀则 MCP 不可见、不可调
            tool_allowlist=["query_order", "query_weather", "maps_*"],
            policy_set="default",
            budget=BudgetPolicy(max_tool_calls=20, max_tokens=8000),
        ),
    )
    registry.register(
        "knowledge",
        AgentDefinition(
            id="knowledge",
            executor=KnowledgeExecutor(),
            tool_allowlist=[],
            policy_set="default",
            budget=BudgetPolicy(max_tool_calls=None, max_tokens=settings.rag_run_token_budget),
        ),
    )
    registry.register(
        "alarm",
        AgentDefinition(
            id="alarm",
            executor=AlarmExecutor(),
            tool_allowlist=[],
            policy_set="default",
            budget=BudgetPolicy(max_tool_calls=None, max_tokens=6000),
        ),
    )
    registry.register(
        "echo",
        AgentDefinition(
            id="echo",
            executor=EchoExecutor(),
            tool_allowlist=[],
            policy_set="default",
            budget=BudgetPolicy(max_tool_calls=None, max_tokens=500),
        ),
    )
    return registry


_builtin_registry: AgentRegistry | None = None


def get_builtin_agent_registry() -> AgentRegistry:
    """进程内单例：只注册一次，避免每个请求 new 三个 Executor。"""
    global _builtin_registry
    if _builtin_registry is None:
        _builtin_registry = register_builtin_agents(AgentRegistry())
    return _builtin_registry
