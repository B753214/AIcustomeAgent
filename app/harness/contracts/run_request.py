from typing import Any

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    """通用 Agent 运行请求。

    - agent_id 允许为空，Router 可以在分发时填入。
    - options 保留扩展空间（超时、temperature、stream 等都可以塞这里）。
    """

    agent_id: str | None = Field(
        default=None,
        description="Agent 标识，如 chat / knowledge / alarm；可由 Router 补全",
    )
    input: str = Field(
        ...,
        description="用户输入文本",
        min_length=1,
    )
    session_id: str | None = Field(
        default=None,
        description="会话 ID，None 表示新会话或无状态调用",
    )
    caller: str = Field(
        default="api",
        description="调用方来源",
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展选项，如 {'stream': True, 'temperature': 0.7}",
    )
