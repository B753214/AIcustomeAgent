from __future__ import annotations

from dataclasses import dataclass, field

from app.harness.contracts import AgentExecutor


@dataclass
class AgentDefinition:
    id: str
    executor: AgentExecutor  # Protocol，任意实现 astream 的对象
    version: str = "1.0"
    prompt_version: str = "1.0"
    tool_allowlist: list[str] = field(default_factory=list)
    model_roles: dict[str, str] = field(default_factory=dict)
    policy_set: str = "default"


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
    """
    from app.agents.harness_alarm.executor import AlarmExecutor
    from app.agents.harness_chat.executor import ChatExecutor
    from app.agents.harness_echo.executor import EchoExecutor
    from app.agents.harness_knowledge.executor import KnowledgeExecutor

    registry.register("chat", AgentDefinition(id="chat", executor=ChatExecutor()))
    registry.register(
        "knowledge",
        AgentDefinition(id="knowledge", executor=KnowledgeExecutor()),
    )
    registry.register("alarm", AgentDefinition(id="alarm", executor=AlarmExecutor()))
    registry.register("echo", AgentDefinition(id="echo", executor=EchoExecutor()))
    return registry


_builtin_registry: AgentRegistry | None = None


def get_builtin_agent_registry() -> AgentRegistry:
    """进程内单例：只注册一次，避免每个请求 new 三个 Executor。"""
    global _builtin_registry
    if _builtin_registry is None:
        _builtin_registry = register_builtin_agents(AgentRegistry())
    return _builtin_registry
