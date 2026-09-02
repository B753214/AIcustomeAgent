# 闲聊 Agent → ReAct（可查活动）计划

跟做方式：**分日交付**；对话说 **「开始 Chat-ReAct-DayN」**。

目标：将 `intent=chat` 从「单轮生成」升级为 **ReAct（推理 + 调工具）**，至少能 **查活动**；无工具需求时仍可直接闲聊。

---

## 一、结论摘要

| 项 | 决策 |
|----|------|
| 改哪条路径 | **LangChain 旁路**的 `chat`（`CHAT_PROMPT \| llm`） |
| Crew 路径 | **可选同步**：执行员可挂同一套活动工具；不强制先改 Crew |
| 框架 | LangChain **create_react_agent / AgentExecutor**（或等价 Tool-calling Agent）；优先 Tool-calling 若模型对 ReAct 文本格式不稳 |
| 活动数据 | Day1 **Mock**；DayN 再接真实活动 API |
| 明确不做 | 不把 knowledge/order/alarm 整条改成 ReAct；不改告警流水线 |

**意图边界（保持）：**

- 退货规则 / FAQ → 仍 `knowledge`（RAG）
- 订单号 / 物流 → 仍 `order`
- 告警字段+链接 → 仍 `alarm`
- 打招呼、闲聊、**问活动/优惠/运营位** → `chat`（本计划）

---

## 二、目标架构

```text
intent=chat
  → Chat ReAct Agent
       tools: query_activity（必做）
              （可选）get_hot_topics / search_knowledge 只读…
  → Thought/Action 或 tool_calls 循环（max_iterations 封顶）
  → 最终中文答复（可带 sources/meta）
```

对比现状：

| | 现在 | 目标 |
|--|------|------|
| chat | 纯 LLM | ReAct + 工具 |
| 活动 | 无 | `query_activity` |
| 无工具需要 | 一次回复 | Agent 直接 Final Answer（0～1 次工具） |

---

## 三、计划表（按日）

| Day | 主题 | 交付物 | 过关标准 |
|-----|------|--------|----------|
| **Day1** | 活动工具（Mock） | `query_activity` + 单元测试 | 给定关键词返回固定活动列表文案 |
| **Day2** | Chat ReAct 核心 | `app/agents/chat_react.py`（或 `services/chat_agent.py`） | 本地脚本：「有什么活动」会调工具；「你好」不调或调完也能礼貌回 |
| **Day3** | 接入 chat 旁路 | `chat.py` 非流式 + 流式（伪流或 token） | `intent=chat` 走 ReAct；FAQ/订单回归不破 |
| **Day4** | 意图与 Prompt | 分类提示补充「问活动→chat」；Agent system prompt | 「双十一有什么活动」→ chat+工具；「怎么退货」→ knowledge |
| **Day5** | 配置 / 降级 / 观测 | `CHAT_REACT_ENABLED`、`max_iterations`、失败回退纯闲聊；trace meta | 关开关=旧行为；工具异常不 500 |
| **Day6** | Crew 对齐（可选） | `query_activity` 注册为 Crew Tool；执行员规则 | `USE_CREW=true` 也能查活动 |
| **Day7** | 真实活动源（可选） | HTTP/BFF 适配；超时与缓存 | Mock 可切换；单测 mock 网络 |
| **Day8** | 收尾 | README / `.env.example` / 单测清单 | 计划打勾；总验收通过 |

建议顺序：**Day1 → Day5 必做**；Day6–7 按是否有真实接口再开。

---

## 四、Day 细节

### Day1 — `query_activity`（Mock）

```text
输入：用户话术或关键词（如「周末」「新人」「满减」）
输出：纯文本活动摘要（标题 / 时间 / 规则 / 入口说明）
落点：app/agents/tools.py（与 query_order 同层）或 app/agents/activity.py
```

- [x] Mock 3～5 条活动
- [x] 无匹配时友好提示「暂无相关活动」
- [x] `tests/test_activity_tool.py`

### Day2 — ReAct 封装

- [ ] Agent + tools 列表（至少 `query_activity`）
- [ ] `max_iterations`（建议 3～5）
- [ ] 解析失败 / 超轮次 → 降级一句礼貌回复
- [ ] 返回结构对齐：`{ reply, intent: chat, sources?, meta: { engine: chat_react, tool_calls? } }`

### Day3 — 接入 `chat.py`

替换点（概念上）：

```text
intent == chat:
  if settings.chat_react_enabled:
      run_chat_react(message, history)
  else:
      CHAT_PROMPT | llm   # 旧路径
```

- [ ] `run()` / `run_stream`（或 astream）都接上
- [ ] 流式：无原生 token 时用「整段 chunk」或伪流，与现有 SSE 事件兼容

### Day4 — 意图边界

- [ ] `INTENT_PROMPT`：明确「查活动/优惠/运营」→ `chat`（不要 knowledge）
- [ ] Agent 提示：需要活动信息必须先调 `query_activity`；禁止编造活动名/时间
- [ ] 回归样例表（见第六节）

### Day5 — 开关与稳定性

| 配置 | 含义 | 默认 |
|------|------|------|
| `CHAT_REACT_ENABLED` | 闲聊是否走 ReAct | `true`（或先 `false` 灰度） |
| `CHAT_REACT_MAX_ITERATIONS` | 最大推理轮次 | `4` |
| （可选）`ACTIVITY_API_BASE` | 真实活动源 | 空=Mock |

- [ ] 工具异常 → 回退纯 LLM 闲聊或固定文案，不抛 500
- [ ] `traces` / `meta` 记录是否调了工具

### Day6 — Crew（可选）

- [ ] `query_activity_tool = tool(...)(query_activity)`
- [ ] 执行员：闲聊/问活动时可调该工具
- [ ] 与 LangChain ReAct **共用同一函数**，避免两套 Mock

### Day7 — 真实接口（可选）

- [ ] Adapter：`fetch_activities(keyword) -> list[dict]`
- [ ] 超时、空结果、鉴权失败处理
- [ ] 短 TTL 缓存（可选）

### Day8 — 文档与验收

- [ ] README：闲聊 ReAct、活动工具、开关
- [ ] `.env.example` 补配置
- [ ] 总验收清单勾选

---

## 五、文件落点（预估）

| 文件 | 动作 |
|------|------|
| `app/agents/tools.py` 或 `activity.py` | `query_activity` |
| `app/agents/chat_react.py` | ReAct / Tool-calling Agent |
| `app/services/chat.py` | chat 分支接入 |
| `app/agents/crew.py` / `tools.py` | Day6 挂工具 |
| `app/config.py` + `.env.example` | 开关 |
| `tests/test_chat_react.py` 等 | 单测（mock LLM/工具） |
| `plan/进度.md`（可选） | 同步「下一步」 |

---

## 六、验收样例

| 用户话 | 期望 intent | 期望行为 |
|--------|-------------|----------|
| 你好 | chat | 可不调工具，礼貌回复 |
| 最近有什么活动？ | chat | 调用 `query_activity`，答复含 Mock/真实活动 |
| 新人有什么优惠？ | chat | 调工具，匹配新人活动 |
| 怎么申请退货？ | knowledge | **不**走 chat ReAct |
| 查一下订单 202608090001 | order | 不走 chat |
| 告警字段+info-plate 链接 | alarm | 不走 chat |

---

## 七、风险与约束

1. **模型格式**：部分模型对经典 ReAct 文本格式不稳定 → 优先 **bind_tools / Tool-calling Agent**，对外仍称「可调工具的闲聊 Agent」。
2. **与 knowledge 抢意图**：活动文案若进了知识库，分类可能偏 knowledge → Day4 规则写死「活动/优惠优先 chat」。
3. **延迟**：ReAct 多 1～N 次 LLM；用 `max_iterations` + 早停。
4. **编造活动**：Prompt 强制「无工具结果不得虚构活动」；单测覆盖。

---

## 八、打勾进度

- [ ] Chat-ReAct-Day1 活动 Mock 工具
- [ ] Chat-ReAct-Day2 ReAct 核心
- [ ] Chat-ReAct-Day3 接入 chat 旁路
- [ ] Chat-ReAct-Day4 意图与 Prompt
- [ ] Chat-ReAct-Day5 开关 / 降级 / 观测
- [ ] Chat-ReAct-Day6 Crew 对齐（可选）
- [ ] Chat-ReAct-Day7 真实活动源（可选）
- [ ] Chat-ReAct-Day8 收尾

---

## 九、你下一步

说：**「开始 Chat-ReAct-Day1」**（或「开始 Day1」）。

若活动已有真实 API 文档，Day1 可改为「接口契约 + Mock 适配同一签名」，Day7 只换实现。
