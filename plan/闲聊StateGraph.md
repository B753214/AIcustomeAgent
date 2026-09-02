# 闲聊 → 手写 LangGraph StateGraph（你来改）

提示词：`开始 Chat-SG-DayN`  

目标：不用 `create_agent` / `create_react_agent` 预置图，**自己 `StateGraph` 定义节点和边**。  
对外仍暴露 `run_chat_react` / `iter_chat_react`（或改名后改 `chat.py` 一处引用）。

现状：`chat_react.py` 已接入手写 `chat_graph`（Day5 完成）；流式仍整段 `ainvoke` 假 SSE。  
工具保持：**`query_order` + `query_weather`**（含 `[TOOL_ERROR]` 约定）；高德 MCP 见 Day7。

---

## 一、目标图（你要画出来的）

```text
START
  → call_model          # bind_tools(LLM) + system
  → should_continue     # 条件边
        ├─ tools → call_tools → call_model   # 环
        └─ end   → END
```

建议在边或 `call_tools` 内加约束：

- 同一工具连续失败（`[TOOL_ERROR]`）≥ **N（建议 1）** → 不再调工具，走总结/结束  
- 总步数：`ainvoke(..., config={"recursion_limit": M})`（建议 8～12）

```text
State 建议字段：
  messages: list[BaseMessage]
  tool_errors: list[str]      # 可选，累计 [TOOL_ERROR]
  tool_fail_counts: dict      # 可选，{tool_name: n}
```

---

## 二、计划表

| Day | 主题 | 你改哪些 | 做什么 | 过关 |
|-----|------|----------|--------|------|
| **Chat-SG-Day1** | State + 空图骨架 | 新文件如 `chat_graph.py`（或改 `chat_react.py`） | 定义 `TypedDict`/`MessagesState` 扩展；`StateGraph(State)`；`add_node` 两个占位；`add_edge` / `add_conditional_edges`；`compile()` | `graph.get_graph().nodes` / `.edges` 能打印出 `call_model`、`tools`（或你起的名字） |
| **Chat-SG-Day2** | `call_model` 节点 | 同文件 | `llm.bind_tools(tools)`；system 用现有 `CHAT_REACT_SYSTEM`；读 `state["messages"]`，返回 `{"messages": [AIMessage]}` | 无工具问题时直接出最终 AI 文本 |
| **Chat-SG-Day3** | `call_tools` + 条件边 | 同文件 | 用 `ToolNode(tools)` **或**自写执行：扫 `tool_calls` → 调工具 → `ToolMessage`；失败结果必须带 `[TOOL_ERROR]` | 「杭州天气」无 Key 时 ToolMessage 含 `[TOOL_ERROR]` |
| **Chat-SG-Day4** | 失败不瞎重试 | 同文件 + 可选 config | 统计连续/同名工具错误次数；≥1（可配置）则 `should_continue` 强制 `end`；`recursion_limit` 写入 `ainvoke` | 失败不会无限循环调天气 |
| **Chat-SG-Day5** | 替换入口 | `chat_react.py` / `chat.py` | `_build_agent` 改为手写 `compile()` 图；删掉 `create_agent`；`run_*` 返回形状不变（`meta.tool_calls` / `tool_errors`） | 单测 + 手测订单/天气/你好 |
| **Chat-SG-Day6** | SSE（节点级） | `iter_chat_react` | `astream(stream_mode="updates")`：call_tools→`stage:tool`；结束→整段 `token`+`result` | 调工具时先出现 tool stage，再出最终回复；不 500 |
| **Chat-SG-Day6b** | SSE（token 级） | `iter_chat_react` / 可选改 `call_model` | `astream_events` 听 `on_chat_model_stream`，或节点内 `model.astream`；逐段 `yield token` | 「你好」几个字几个字往外冒 |
| **Chat-SG-Day7** | 高德 MCP（可选） | `amap_mcp.py`、`chat_graph._chat_tools`、config、`.env` | `langchain-mcp-adapters` 拉 maps_*；`amap_mcp_enabled`+Key 才并入 tools；无 Key 仅本地 order/weather | 「杭州天气/周边」可调 maps_*；关开关行为与现在一致 |
| **Chat-SG-Day8** | 收尾 | README、计划打勾 | 写明：闲聊=手写 StateGraph；高德为可选 MCP；预置 create_agent 已废弃 | 回归 knowledge/alarm |

**必做 Day1–5。** Day6 节点流建议做；**Day6b token 流稍后**；Day7 有高德 Key 再做。

---

## 三、实现步骤（按日拆解，你来写）

### Day1 — 骨架（先能看见点边）

1. `from langgraph.graph import StateGraph, START, END`  
2. `from langgraph.graph.message import add_messages`（messages 字段常用 reducer）  
3. 定义 State（至少 `messages`）  
4. `g = StateGraph(State)`  
5. `g.add_node("call_model", ...)` / `g.add_node("call_tools", ...)`（可先 `lambda s: s` 占位）  
6. `g.add_edge(START, "call_model")`  
7. `g.add_conditional_edges("call_model", should_continue, {"tools": "call_tools", "end": END})`  
8. `g.add_edge("call_tools", "call_model")`  
9. `app = g.compile()` → 打印 nodes/edges  

过关：业务逻辑可以假，**图结构必须真。**

### Day2 — call_model

1. 复用 `_build_llm()`、`_chat_tools()`、`CHAT_REACT_SYSTEM`  
2. `model = llm.bind_tools(tools)`  
3. 组装：`[SystemMessage(system)] + state["messages"]`（注意别和历史 System 重复）  
4. `response = await model.ainvoke(...)`  
5. `return {"messages": [response]}`  

### Day3 — call_tools

**推荐 A：** `from langgraph.prebuilt import ToolNode`  
`ToolNode(_chat_tools())` 当节点（仍算你构图，只是工具执行器用预置）。  

**推荐 B（更可控）：** 自写节点：读最后一条 AI 的 `tool_calls` → 调 `_wrap_tool` 后的函数 → 追加 `ToolMessage`。  

失败：继续现有 `[TOOL_ERROR]` 包装。

### Day4 — should_continue 策略

```text
若最后 AI 无 tool_calls → "end"
若某工具错误次数 >= max_tool_retries（默认 1）→ "end"
否则 → "tools"
```

`ainvoke(state, config={"recursion_limit": 8})`。

### Day5 — 接线

- `run_chat_react`：构造初始 `{"messages": [HumanMessage(...)]}` → `graph.ainvoke`  
- 从最终 `messages` 抽 reply / tool_calls / tool_errors（可复用现有 helper）  
- **删除** `create_agent` 引用  

### Day6 — 流式

现状：`iter_chat_react` 内部仍 `await run_chat_react`（整图跑完再吐 stage/token），前端看起来像流，实际不是边跑边推。

目标：改用 `chat_graph.astream`（updates 模式即可）：

```text
yield stage chat_react
async for chunk in chat_graph.astream(state, config=..., stream_mode="updates"):
  # chunk 形如 {"call_model": {...}} 或 {"call_tools": {...}}
  若节点 call_tools → yield stage tool（可扫 ToolMessage / tool_calls 名）
  若 ToolMessage 含 [TOOL_ERROR] → yield stage tool_error
  若节点 call_model 且最终 AI 有正文 → 可先缓存，循环后再 yield token
循环结束 → 用与 run_chat_react 相同的 helper 拼 result，yield result
```

注意：

- `run_chat_react` 可继续 `ainvoke`（非流式接口）；只改 `iter_chat_react`
- 事件字段保持：`type=stage|token|result`，与 `chat.py` 的 `run_astream` 兼容
- 本轮 **不做** token 级（几个字几个字）；整段最终 `token` 即可过关 → token 级见 **Day6b**

### Day6b — token 流（稍后）

- `async for ev in chat_graph.astream_events(...)`，过滤 `event == "on_chat_model_stream"`  
- 或 `call_model` 内对 `model.astream` 边收边写（图内流式更绕，优先 events）  
- 每个 delta → `yield {"type": "token", "content": piece}`；结束仍 `yield result`  
- 注意：有 tool_calls 的中间 AI 不要当最终回复刷 token

### Day7 — 高德 MCP（可选）

1. 补全 `app/agents/alarm/amap_mcp.py`（或挪到 `app/agents/amap_mcp.py`）：`MultiServerMCPClient` / Streamable HTTP → `get_tools()`  
2. URL / Key：只用 `settings.amap_mcp_url`、`amap_maps_api_key`；**禁止写进仓库**  
3. `chat_graph._chat_tools`：本地 tools +（若 enabled）`await get_amap_tools()`；图若需异步拉工具，可在 `build_chat_graph` 外缓存或节点内惰性加载  
4. system 提示：有 maps_* 时引导天气/地理可用高德工具；无 MCP 时仍用 `query_weather`  
5. `.env.example`：`AMAP_MCP_ENABLED`、`AMAP_MAPS_API_KEY`  

过关：关开关 = 行为不变；开开关 + Key → 轨迹里出现 maps_*（或官方工具名）。

### Day8 — 收尾

README / 计划打勾；回归 knowledge、alarm。

---

## 四、与当前代码的关系

| 可复用 | 不要再依赖 |
|--------|------------|
| `CHAT_REACT_SYSTEM`、`[TOOL_ERROR]`、`_wrap_tool`、`query_order` / `query_weather` | `create_agent(...)` 作为主循环 |
| `run_chat_react` 返回 dict 形状；SSE 事件约定 | 指望预置图「自动」限重试 |
| `config.amap_mcp_*`、`amap_mcp.py` 空壳 | 无 Key 时强依赖高德 |

---

## 五、验收

| 场景 | 期望 |
|------|------|
| 打印 graph | 能看到你命名的 node 与边 |
| 你好 | 不调工具，直接 end |
| 查订单 | 走 call_tools → query_order |
| 天气无 Key | ToolMessage 含 `[TOOL_ERROR]`；最多再进 tools 有限次后 end |
| Day6 流式 | 调工具时先出现 `stage:tool`，再逐段 `token`，最后 `result` |
| Day6b token | 「你好」等多条小 `token`，不是整段一次性 |
| Day7 高德 | 开关关=仅本地工具；开+Key 可见 maps_* |
| knowledge / alarm | 不受影响 |

---

## 六、打勾

- [x] Chat-SG-Day1 State + 空图骨架（能打印点边）
- [x] Chat-SG-Day2 call_model
- [x] Chat-SG-Day3 call_tools + 条件边
- [x] Chat-SG-Day4 失败重试上限 + recursion_limit
- [x] Chat-SG-Day5 替换 create_agent 入口
- [x] Chat-SG-Day6 SSE astream（节点 updates）
- [x] Chat-SG-Day6b SSE token 流
- [x] Chat-SG-Day7 高德 MCP（可选）
- [x] Chat-SG-Day8 收尾

---

## 七、你下一步

Chat-SG 已完成。告警线可说：**「开始 Alarm-PER-Day1」**。
