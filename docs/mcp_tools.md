# Harness MCP 工具接入

高德 MCP 的发现和缓存位于 `app/harness/tools/mcp.py`。首次进入对话时，
`ensure_chat_tools()` 将远端工具定义及异步调用适配器注册到当前 Run 使用的
`ToolRegistry`。关闭开关或未配置 Key 时跳过远端连接；发现失败时允许下次重试。
重复准备不会重复注册，同名冲突不会覆盖已有工具。

本地工具与 MCP 工具在模型调用前统一由 `list_model_tools()` 按 Agent
`tool_allowlist` 筛选，再通过 `bind_tools()` 暴露给模型。高德工具需要显式
允许 `maps_*` 或具体工具名；发现和注册本身不会授予调用权限。

Harness 对话路径中的实际调用统一经过 `ToolRunner`，复用参数必填检查、
白名单、单次超时、取消检查和输出截断；原 MCP 工具负责远端参数处理。
MCP 工具默认不声明幂等、不增加自动重试。现有成功调用预算计数保持原行为。

旧 Crew/非 Harness 入口通过兼容接口复用 Harness 的 MCP 发现结果。
告警 Workflow 的专用 MCP 抓取顺序不受本次对话工具接入调整影响。

离线验证：`python -m pytest tests/test_mcp_harness.py tests/test_chat_tool_harness.py -q`。
