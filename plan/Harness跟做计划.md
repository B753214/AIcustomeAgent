# Harness 跟做计划（完整版）

提示词：`开始 Harness-H0-1` / `开始 Harness-H1` / `完成 Harness-H0-1`

> **蓝图原文（勿改）：** [Harness改造计划.md](./Harness改造计划.md)  
> **本文：** 按旧蓝图 H0～H7 **逐步跟做**的完整施工单。  
> 另有精简执行版 [AgentRuntime改造计划.md](./AgentRuntime改造计划.md)；**本仓库当前主跟做以本文为准（完整旧计划）。**

---

## 0. 你要先建立的概念

```text
Harness / Runtime  = 套在所有 Agent 外的统一运行壳（Run、事件、策略、取消）
Executor           = 某个领域 Agent 的执行器（Chat / Knowledge / Alarm）
Registry           = 注册表：有哪些 Agent、Tool、Model、Policy
RunEvent           = 标准事件（JSON 与 SSE 都消费同一条流）
Checkpoint         = 可恢复的工作状态（尤其 Alarm），不是聊天记录
```

原则（与蓝图一致）：

- **模块化单体**，不拆微服务。
- Chat 继续 LangGraph ReAct；Alarm 继续 Pipeline + Replan。
- JSON 与 SSE **同一执行链**。
- 渐进迁移；旧 API 兼容；特性开关切流。
- CrewAI：插件接入或下线，禁止长期不可测双轨。

目标目录（最终态，中间可先只建 `harness/`）：

```text
app/harness/{contracts,runtime,registry,policies,observability,storage}
app/agents/{chat,knowledge,alarm}
app/integrations/   # 可后期再搬
app/api/            # 可后期再搬
```

---

## 1. 总览与里程碑

| 阶段 | 名称 | 建议 | 里程碑 |
|---|---|---:|---|
| **H0** | 基线稳定 | 2～3 天 | M1：可复现安装/测试/黄金用例 |
| **H1** | 核心契约 | 3～4 天 | 契约与单测齐备 |
| **H2** | Runtime 门面 | 4～6 天 | M2：JSON/SSE 同一 Runtime |
| **H3** | Registry / Gateway | 4～6 天 | Agent/Tool/Model 可注册 |
| **H4** | Agent 迁移 | 7～10 天 | M3：三 Agent + Router 可插拔 |
| **H5** | 状态与恢复 | 5～7 天 | Alarm Checkpoint 可恢复 |
| **H6** | 策略与观测 | 5～7 天 | M4：Policy + 统一 Trace |
| **H7** | 评测与扩展 | 3～5 天 | M5：新 Agent 不改 Runtime |

一人全职约 **5～7 周**。打勾跟踪：每完成一步把下方清单里的 `- [ ]` 改成 `- [x]`。

---

## 2. 进度清单

### H0 基线稳定

- [x] H0-1 统一 Python / Conda 环境说明
- [x] H0-2 依赖 UTF-8 与分层 requirements 可安装
- [x] H0-3 Settings 与 `.env.example` 对齐
- [x] H0-4 PG / Milvus 必选与降级语义写清
- [x] H0-5 CI + 全部离线测试通过
- [x] H0-6 Chat / RAG / Alarm 黄金场景快照

### H1 核心契约

- [x] H1-1 `RunRequest`
- [x] H1-2 `RunContext`
- [x] H1-3 `RunEvent`
- [x] H1-4 `RunResult`
- [x] H1-5 `AgentExecutor` 协议
- [x] H1-6 `ToolSpec`
- [x] H1-7 `HarnessError` + 事件类型常量
- [x] H1-T 契约单测

### H2 Runtime 门面

- [ ] H2-1 `AgentRuntime.execute_stream`
- [ ] H2-2 JSON 消费同一事件流
- [ ] H2-3 FastAPI 降为 Transport Adapter（可先接 Fake/单 Agent）
- [ ] H2-4 取消语义
- [ ] H2-5 SSE 短事务边界

### H3 Registry 与 Gateway

- [ ] H3-1 Agent Registry
- [ ] H3-2 Model Gateway（router/worker/judge）
- [ ] H3-3 Tool Registry
- [ ] H3-4 Tool Runner（校验/超时/类型化错误/事件）
- [ ] H3-5 Policy Registry（先注册结构，策略可薄）

### H4 Agent 迁移

- [ ] H4-1 ChatExecutor + 特性开关
- [ ] H4-2 KnowledgeExecutor
- [ ] H4-3 AlarmExecutor
- [ ] H4-4 Router 抽出
- [ ] H4-5 CrewAI：插件或下线决策并落地

### H5 状态与恢复

- [ ] H5-1 Run 表与仓储
- [ ] H5-2 Checkpoint 接口 + PG JSONB
- [ ] H5-3 Artifact 元数据
- [ ] H5-4 Trace Event 落库（初期 PG）
- [ ] H5-5 Alarm 可恢复步骤 + 幂等键 + 恢复测试

### H6 策略与观测

- [ ] H6-1 Auth / Budget / Retry / Timeout / Cache / Data / Tool Policy
- [ ] H6-2 Policy Chain 接入 Runtime
- [ ] H6-3 Dashboard / SSE 只消费标准事件
- [ ] H6-4 脱敏与审计

### H7 评测与扩展

- [ ] H7-1 Contract / Unit / Golden / Replay / Failure 测试层
- [ ] H7-2 Eval 指标挂钩（RAG/路由/工具/Alarm）
- [ ] H7-3 示例新 Agent（只注册、不改 Runtime）

---

## 3. 分步施工单（跟做明细）

### H0：基线稳定

| 编号 | 你改/查哪些 | 做什么 | 过关 |
|---|---|---|---|
| **H0-1** | README、可选 `docs/env.md`、`environment.yml` 或版本说明 | 写明支持的 Python（建议 3.12）、Conda/venv 步骤、一次安装命令 | 按文档在干净环境能装起来 |
| **H0-2** | `requirements.txt` / `-dev` / `-extra` / `-eval` | 确认 UTF-8；分层依赖可 `pip install -r`；去掉坏编码 | 本机安装成功；核心测试依赖齐 |
| **H0-3** | `app/config.py`、`.env.example` | 字段与环境变量名对照表；缺关键项启动失败信息明确 | 复制 example 后能启动或得到清晰缺项 |
| **H0-4** | `main` lifespan、`/health`、README | 写清 PG/Milvus 是否必选；缺失时 fail-fast 还是降级 | 行为与文档一致 |
| **H0-5** | `.github/workflows` 或现有 CI、`tests/` | 跑完全部离线测试；修红；CI 分支正确 | `pytest` 离线子集绿 |
| **H0-6** | `tests/golden/` 或 `eval/fixtures/` | 固化 Chat / RAG / Alarm 各至少 2 组：输入、关键事件、期望片段 | 文件可被后续阶段引用 |

### H1：核心契约

在 `app/harness/contracts/` 落地（Pydantic 模型 + Protocol）。  
**本阶段只定义「形状」与单测，不接 Runtime、不改业务路由。**

#### H1 模块总览（先建立概念）

```text
外部调用方                执行过程中                 执行结束
─────────                ─────────                 ─────────
RunRequest  ──创建→  RunContext ──产生→ RunEvent* ──汇总→ RunResult
                              │
                              └── AgentExecutor.astream(ctx)
                                        │
                                   按 ToolSpec 调工具
                                   失败用 HarnessError 分类
```

| 契约 | 一句话职责 | 谁创建 / 谁消费 |
|---|---|---|
| **RunRequest** | 「这次想跑什么」的入参 | API/Eval/CLI 创建；Runtime 接收 |
| **RunContext** | 「这次正在跑」的运行态 | Runtime 创建；Executor / Policy / ToolRunner 读写 |
| **RunEvent** | 过程中的标准事件（SSE/日志/看板同一套） | Executor/Runtime 发出；前端与 JSON 聚合器消费 |
| **RunResult** | 跑完后的统一结果 | Runtime 从事件流汇总；API 映射成旧 ChatResponse |
| **AgentExecutor** | 某个 Agent 的执行接口 | Chat/Knowledge/Alarm 各自实现；Runtime 只认接口 |
| **ToolSpec** | 工具的静态说明书 | Registry 保存；ToolRunner 按说明书校验/超时 |
| **HarnessError** | 错误分类，避免只靠字符串前缀 | ToolRunner/Runtime 抛出或写入 event/result |

**为什么要拆 Request / Context / Result / Event？**  
- Request 是调用方可见、可落审计的「意图」；不要把 deadline、权限缓存塞进去。  
- Context 是进程内运行态，可含不可序列化或不该回传客户端的东西（后续可扩展 cancellation）。  
- Event 让 JSON 与 SSE **共用一条执行链**：SSE 原样推事件，JSON 收齐再变成 Result。  
- Result 对齐现有 `reply/sources/intent`，迁移期不必改前端契约。

---

#### H1-1 `RunRequest` — 入参

**功能：** 描述一次 Agent 调用的输入；可校验、可序列化、可进日志（脱敏后）。  
**文件建议：** `app/harness/contracts/run_request.py`

| 字段 | 类型建议 | 默认 | 为什么要有 |
|---|---|---|---|
| `agent_id` | `str \| None` | `None` | 指定跑哪个 Executor；允许空则由 Router 填写 |
| `input` | `str` | 必填，`min_length=1` | 用户原文；避免空跑 |
| `session_id` | `str \| None` | `None` | 关联短时记忆 / 会话表 |
| `caller` | `str` | `"api"` | 区分 `api` / `eval` / `cli` |
| `options` | `dict[str, Any]` | `{}`（`default_factory`） | 扩展口，避免每加开关就改模型 |

**过关：** 可 `model_dump`；空 `input` 校验失败。

---

#### H1-2 `RunContext` — 运行态

**功能：** 一次 Run 执行期间的上下文；**只活在 Runtime 内**，不要放进 Agent Registry。  
**文件建议：** `app/harness/contracts/run_context.py`

| 字段 | 类型建议 | 默认 | 为什么要有 |
|---|---|---|---|
| `run_id` | `str` | 必填 | 贯穿事件、日志、落库的主键 |
| `trace_id` | `str \| None` | `None` | 跨段调用关联；可只用 run_id |
| `request` | `RunRequest` | 必填 | 原始入参；Executor 读 input/options |
| `messages` | `list[dict[str, Any]]` | `[]` | 已装配的对话历史 |
| `permissions` | `dict[str, Any]` | `{}` | 本 Run 允许的 Agent/工具范围 |
| `deadline` | `datetime \| None` | `None` | 整次 Run 截止时间 |
| `budget` | `dict[str, Any]` | `{}` | 如 `max_tool_calls` / `max_tokens` |
| `metadata` | `dict[str, Any]` | `{}` | 路由结果、开关、调试标记 |

**过关：** 能挂上 `RunRequest` 构造；dict/list 用 `default_factory`。

---

#### H1-3 `RunEvent` — 过程事件

**功能：** 执行过程的标准通知。Dashboard / SSE / Trace 都消费它。  
**文件建议：** `app/harness/contracts/run_event.py`

| 字段 | 类型建议 | 默认 | 为什么要有 |
|---|---|---|---|
| `type` | `str` | 必填 | 事件种类；优先用下方常量 |
| `timestamp` | `datetime` | `default_factory` → UTC now | 排序与耗时 |
| `run_id` | `str` | 必填 | 归属哪一次 Run |
| `sequence` | `int`（`ge=0`） | 必填 | 同 run 内递增，便于排序去重 |
| `payload` | `dict[str, Any]` | `{}` | token / 工具名 / step / 错误摘要 |
| `visibility` | `Literal["public", "internal"]` | `"public"` | 控制是否透出给前端 |

**约定事件名常量（`str` + 常量即可，不必强 Enum）：**  
`run.started`、`route.selected`、`model.started`、`model.token`、`model.completed`、`tool.started`、`tool.completed`、`tool.failed`、`workflow.step`、`run.completed`、`run.failed`。

**过关：** 模型可构造；事件名常量可 import。

---

#### H1-4 `RunResult` — 终态结果

**功能：** 一次 Run 的最终对外结果；可映射现有 `ChatResponse`。  
**文件建议：** `app/harness/contracts/run_result.py`

| 字段 | 类型建议 | 默认 | 为什么要有 |
|---|---|---|---|
| `status` | `Literal["succeeded", "failed", "cancelled"]` | 必填 | 机器可分支；超时用 `failed` + `error.type=timeout` |
| `output` | `str \| None` | `None` | 主回复（≈ `reply`） |
| `sources` | `list[dict[str, Any]]` | `[]` | RAG 引用（API 层可再压成 str 列表） |
| `artifacts` | `list[dict[str, Any]]` | `[]` | 大产物引用（报告路径等） |
| `usage` | `dict[str, Any]` | `{}` | tokens / tool_calls / latency_ms |
| `error` | `dict[str, Any] \| None` | `None` | 结构化错误，对齐 HarnessError |
| `metadata` | `dict[str, Any]` | `{}` | intent / engine / cache_hit |

**过关：** 能覆盖旧 chat 成功/失败响应的映射需求。

---

#### H1-5 `AgentExecutor` — 执行器协议

**功能：** 规定「领域 Agent 如何被 Runtime 调用」。  
**文件建议：** `app/harness/contracts/executor.py`  
**类型：** `typing.Protocol`

```text
async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]: ...
```

| 约定 | 为什么 |
|---|---|
| 只通过 Context 取输入 | 禁止 Executor 旁路全局状态 |
| 只产出 RunEvent | JSON/SSE 才能统一 |
| 取消信号由 H2 挂到 Context | 客户端断开后停 model/tool |
| 不强制返回 RunResult | 由 `run.completed` / `run.failed` payload 聚合 |

**过关：** Protocol + 文档字符串清晰。

---

#### H1-6 `ToolSpec` — 工具说明书

**功能：** 工具静态元数据；与函数实现分离。  
**文件建议：** `app/harness/contracts/tool_spec.py`

| 字段 | 类型建议 | 默认 | 为什么要有 |
|---|---|---|---|
| `name` | `str` | 必填 | 唯一名（如 `query_order`） |
| `version` | `str` | `"1.0"` | schema 变更可灰度 |
| `description` | `str` | 必填 | 给模型/文档看 |
| `input_schema` | `dict[str, Any]` | `{}` | JSON Schema 或等价参数描述 |
| `permissions` | `dict[str, Any]` | `{}` | 哪些 caller/agent 能调 |
| `timeout_sec` | `float`（`gt=0`） | `30.0` | 单工具超时（对齐 `TOOL_TIMEOUT_SEC`） |
| `retry` | `int`（`ge=0`） | `0` | 额外重试次数 |
| `idempotent` | `bool` | `False` | 重试/恢复是否安全 |

**过关：** 能描述 `query_order` / `query_weather` 至少一个。

---

#### H1-7 `HarnessError` + 事件常量

**功能：** 把失败分成可处理的类别，替代只靠 `[TOOL_ERROR]` 字符串前缀。  
**文件建议：** `app/harness/contracts/harness_error.py`  
（事件名常量已在 `run_event.py`，本步重点是 Error。）

| 符号 | 类型建议 | 说明 |
|---|---|---|
| `HarnessErrorCategory` | `StrEnum` | `validation` / `model` / `tool` / `policy` / `timeout` / `storage` / `internal` |
| `HarnessError` | 继承 `Exception` 或 Pydantic 模型 | 至少含 `category`、`message`；可选 `details: dict[str, Any]` |

| 类别 | 典型场景 |
|---|---|
| `validation` | 参数不合法 |
| `model` | LLM 调用失败 |
| `tool` | 工具业务/执行失败 |
| `policy` | 权限/预算拒绝 |
| `timeout` | Run 或工具超时 |
| `storage` | PG/Milvus 读写失败 |
| `internal` | 未归类内部错误 |

**过关：** Enum 与 Error 可 import；能写入 `RunResult.error` / `tool.failed` payload。

---

#### H1 任务勾选与过关表

| 编号 | 内容 | 过关 |
|---|---|---|
| **H1-1** | `RunRequest` | 可序列化/校验 |
| **H1-2** | `RunContext` | 运行态字段齐全；引用 Request |
| **H1-3** | `RunEvent` + 事件名常量 | 可构造；常量覆盖约定词表 |
| **H1-4** | `RunResult` | 可映射旧 chat 响应关键字段 |
| **H1-5** | `AgentExecutor` Protocol | 有 `astream` 签名与取消说明 |
| **H1-6** | `ToolSpec` | 能描述现有 tool |
| **H1-7** | `HarnessError` | 七类错误可 import |
| **H1-T** | `tests/test_harness_contracts.py` | 构造/校验/事件枚举单测通过 |

### H2：Runtime 门面

| 编号 | 做什么 | 过关 |
|---|---|---|
| **H2-1** | `AgentRuntime.execute_stream`：校验 → 建 Run →（薄）前置策略 → 调 Executor → 转发事件 | FakeExecutor 能跑通事件序 |
| **H2-2** | `execute()` 内部只消费 `execute_stream` 聚合 `RunResult` | 无第二套业务 if |
| **H2-3** | 选一个端点（建议先 chat）改为 Adapter；特性开关 | 开关开走 Runtime，关走旧路径 |
| **H2-4** | `CancellationToken` / `asyncio.Event`；断开后停 model/tool | 单测或手工验证 |
| **H2-5** | 文档 + 代码：SSE 不用长持有同一 AsyncSession | Code review / 注释约定 |

### H3：Registry、模型与工具

| 编号 | 做什么 | 过关 |
|---|---|---|
| **H3-1** | AgentRegistry：id、版本、Executor、prompt 版本、工具白名单、策略集 | 可注册/获取 Chat 占位 |
| **H3-2** | Model Gateway：按角色创建；流式/结构化/重试/用量 | 现有 `get_llm` 迁入或包装 |
| **H3-3** | Tool Registry：本地/HTTP/MCP/浏览器/RAG | 至少注册订单/天气等现有 tool |
| **H3-4** | Tool Runner：校验、超时、截断、脱敏、类型化错误、打事件 | 替换 chat_graph 内散落调用的一部分 |
| **H3-5** | Policy Registry：先能按 agent 取策略组合 | 即使策略实现仍薄 |

### H4：Agent 迁移

| 编号 | 顺序 | 做什么 | 过关 |
|---|---|---|---|
| **H4-1** | Chat | 包装 LangGraph → `ChatExecutor`；开关 `HARNESS_CHAT=1` | 闲聊/订单/天气/失败/流式与黄金用例等价 |
| **H4-2** | Knowledge | Retriever 可工具化 + `KnowledgeExecutor` | 来源、无答案、流式 |
| **H4-3** | Alarm | Pipeline/Replan → `AlarmExecutor`；step→`workflow.step` | 补页/换 playbook/跳过 |
| **H4-4** | Router | 从 `chat.py` 抽出；发 `route.selected` | 可单测、可回退 |
| **H4-5** | Crew | **决策并执行**：`CrewExecutor` 插件 **或** 文档+开关默认下线 | 无不可测双轨 |

### H5：状态、存储与恢复

| 编号 | 做什么 | 过关 |
|---|---|---|
| **H5-1** | `agent_runs`（或等价）表 + Repository | 每次 Runtime 执行可查 |
| **H5-2** | Checkpoint 接口；PG JSONB 实现 | 能读写 |
| **H5-3** | Artifact 元数据（报告/抓取）；大文件可本地路径 | 告警报告可关联 |
| **H5-4** | 关键 `RunEvent` 落库 | 按 run_id 可回放事件列表 |
| **H5-5** | Alarm：已抓取页、摘要、playbook、replan 次数、已完成步骤、幂等键；仅从可恢复步骤继续 | 恢复测试：不重复危险外部操作 |

### H6：策略与可观测性

| 编号 | 做什么 | 过关 |
|---|---|---|
| **H6-1** | 实现 Auth/Budget/Retry/Timeout/Cache/Data/Tool 策略（可先最小可用） | 单元测试覆盖关键分支 |
| **H6-2** | Policy Chain 挂进 Runtime 前后置钩子 | 超预算/超时有标准错误事件 |
| **H6-3** | Dashboard/SSE 适配标准事件 | 不再依赖各 Agent 私有字典作为唯一来源 |
| **H6-4** | Trace 脱敏；审计字段 | 无 Token/密码进日志 |

### H7：评测与扩展验证

| 编号 | 做什么 | 过关 |
|---|---|---|
| **H7-1** | Contract / Unit / Golden / Replay / Failure 分层补齐 | CI 可跑离线层 |
| **H7-2** | 与现有 `eval/` 对齐：RAG、路由、工具、Alarm 指标 | 有基线数字或报告 |
| **H7-3** | 新增示例 Agent（如 `echo` 或 `summary`）：只加定义+注册 | **禁止**改 Runtime/API/旧 Agent |

---

## 4. 关键验收（整轮结束时）

与蓝图第 5 节一致，必须全部满足：

- 一致性：JSON 与 SSE 最终输出/来源/错误/Trace 一致  
- 扩展性：新 Agent 不改 Runtime；新工具不改 Executor 核心  
- 可靠性：外部调用有超时、错误分类、可配置重试  
- 可恢复性：Alarm 进程重启后可从安全 checkpoint 继续  
- 可观测性：model/tool/step 均有 run_id、耗时、状态  
- 安全性：工具权限可控；Trace 已脱敏  
- 可测试性：核心离线测试不依赖真实 LLM/PG/Milvus/MCP/浏览器  
- 兼容性：`/api/v1/chat`、stream、ingest、analyze 契约兼容  

---

## 5. 明确不做

- 不拆微服务；不自研图引擎；不可视化工作流编辑器  
- 不第一期发独立 SDK；不强制 Alarm→ReAct  
- 不第一阶段上 Kafka/Redis/完整 OTel 平台（Trace 可先 PG）  

---

## 6. 跟做约定

1. 一次只做 **一个编号**（如 H0-1），做完打勾并说 `完成 Harness-H0-1`。  
2. 助手按编号给：**目标 → 改哪些文件 → 具体步骤 → 怎么验收 → 下一步**。  
3. 行为漂移用 H0-6 黄金用例回归。  
4. 大搬家（`integrations/`、`api/`）放在 H4 稳定之后，避免早期大扩散。

---

## 7. 变更记录

| 日期 | 说明 |
|---|---|
| 2026-09-22 | 根据 [Harness改造计划.md](./Harness改造计划.md) 生成完整跟做计划；开始逐步引导自 **H0-1** |
| 2026-09-22 | **完成 H0-1**：README 推荐 3.12 + venv/Conda；新增 `docs/env.md`、`environment.yml` |
| 2026-09-22 | **完成 H0-2**：修复 `requirements.txt` UTF-16 损坏→UTF-8；补齐缺失包分层；`agent-test`(3.12) 四层 `pip install` 通过 |
| 2026-09-22 | **完成 H0-3**：对齐 Settings/`.env.example`；`embedding_*` 可选回落；缺项可读报错；新增 `docs/config.md` |
| 2026-09-22 | **完成 H0-4**：明确 PG/Milvus 双必选；lifespan fail-fast；`/health` 带 required；新增 `docs/deps.md` |
| 2026-09-22 | **完成 H0-5**：修 flaky `query_order`；pytest basetemp；新增 `.github/workflows/offline-tests.yml`；`141 passed` |
| 2026-09-22 | **完成 H0-6**：`tests/golden/{chat,knowledge,alarm}.json` + `test_golden_scenarios.py`（10 passed）；**H0 里程碑完成** |
| 2026-09-22 | 扩充 H1 计划：各契约模块职责 + 字段设计原因（跟做用） |
| 2026-09-22 | H1 字段表补回「类型建议 / 默认」列，并与当前实现对齐 |
| 2026-09-22 | **完成 H1**：contracts 齐备 + `tests/test_harness_contracts.py`（9 passed） |
