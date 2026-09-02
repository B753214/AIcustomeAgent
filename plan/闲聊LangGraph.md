# 闲聊 → LangGraph Agent（你来改）

> **后续：** 若要「自己画点边」，改跟 [闲聊StateGraph.md](./闲聊StateGraph.md)（`开始 Chat-SG-Day1`），用 `StateGraph` 替换本文件的 `create_agent`。


不要用已弃用的 `langchain.agents.AgentExecutor`。

---

## 目标形态

```text
classify → alarm | knowledge | chat
                          ↓
              LangGraph create_react_agent
              tools: query_activity, query_order, [amap…]
              ainvoke / astream
                          ↓
              仍返回 {reply, intent, engine: chat_react, meta}
```

`chat.py` 继续调 `run_chat_react` / `iter_chat_react`，对外接口不变。

---

## 计划表

| Day | 主题 | 你改哪些 | 做什么 | 过关 |
|-----|------|----------|--------|------|
| **Chat-LG-Day1** | 依赖 | `requirements.txt` | 加 `langgraph`（版本跟现有 `langchain>=0.3` 匹配） | `from langgraph.prebuilt import create_react_agent` 能 import |
| **Chat-LG-Day2** | 换循环 | `chat_react.py` | 删手写 for+ToolMessage；`create_react_agent(llm, tools, prompt=…)`；`ainvoke({"messages": [...]})` 取最后一条 AI 回复 | 单测 mock：问好调用具 / 你好不调；行为接近现在 |
| **Chat-LG-Day3** | 轮次与降级 | 同文件 + 可选 config | `recursion_limit` 或等价 max；异常仍返回固定文案，不 500 | 工具死循环被截断 |
| **Chat-LG-Day4** | SSE | `iter_chat_react` | 用 `astream` 映射现有 `stage`/`token`；没有细粒度 token 就整段 chunk | `/api/v1/chat/stream` 闲聊不破 |
| **Chat-LG-Day5** | 高德 MCP（可选） | 新 `amap_mcp.py`、config、`.env` | `langchain-mcp-adapters` Streamable HTTP；`get_tools()` 并进 agent tools；Key 只放 `.env` | 「杭州天气」会调 maps_*；无 Key 时仅本地工具 |
| **Chat-LG-Day6** | 收尾 | README、`.env.example`、单测 | 说明闲聊=LangGraph，告警/RAG=原样 | 回归 knowledge/alarm |

**必做 Day1–4。** Day5 有 Key 再做。

---

## Day2 写法要点（自己查当前 API）

不同小版本函数名可能是 `create_react_agent` 或 `create_agent`。典型骨架：

```python
from langgraph.prebuilt import create_react_agent

agent = create_react_agent(llm, tools, prompt=CHAT_REACT_SYSTEM)
result = await agent.ainvoke({"messages": messages})
reply = result["messages"][-1].content
```

- `tools`：继续用现在的 `StructuredTool.from_function(query_activity / query_order)`  
- `messages`：`System` 若已通过 `prompt=` 注入，就不要重复塞一遍（以你安装版本的文档为准）  
- 从 `result["messages"]` 里可扫 `tool` 名填 `meta.tool_calls`  
- `engine` 保持 `chat_react` 或改成 `langgraph`，和前端约定好即可  

---

## 明确不做

- 不把 RAG / 告警改成 Graph  
- 不上旧 `AgentExecutor`  
- 不把高德 Key 写进仓库  

---

## 验收

| 话 | 期望 |
|----|------|
| 你好 | 可不调工具 |
| 最近有什么活动 | `query_activity` |
| 查订单 202608090001 | `query_order` |
| 怎么申请退货 / 告警字段+链接 | 仍走 knowledge / alarm |

---

## 打勾

- [x] Chat-LG-Day1 依赖
- [x] Chat-LG-Day2 换循环
- [ ] Chat-LG-Day3 轮次降级
- [ ] Chat-LG-Day4 SSE
- [ ] Chat-LG-Day5 高德 MCP（可选）
- [ ] Chat-LG-Day6 收尾
