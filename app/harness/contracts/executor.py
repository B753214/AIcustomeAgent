from __future__ import annotations

from typing import AsyncIterator, Protocol

from .run_context import RunContext
from .run_event import RunEvent


class AgentExecutor(Protocol):
    """领域 Agent 执行器协议。

    实现方只需提供 astream；Runtime 只依赖此接口分发，
    不关心具体是 LangGraph、CrewAI 还是手写 Pipeline。

    约定：
    1. 输入 —— 只从 ctx（RunContext）取数，禁止旁路解析 Request 或读全局可变状态。
    2. 输出 —— 只能 yield RunEvent，供 JSON/SSE 统一消费。
    3. 取消 —— H2 会在 Context 上提供取消信号；实现方应周期性检查并停止后续
       model/tool 调用（具体 API 以 H2 为准，当前不要假定已有 is_cancelled）。
    4. 终态 —— 不要求单独返回 RunResult；run.completed / run.failed 的 payload
       作为 Runtime 聚合 RunResult 的依据。
    """

    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        """执行一次 Run，流式产出标准事件。"""
        ...
