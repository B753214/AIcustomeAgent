# Harness 跟做计划（完整版）

提示词：`开始 Harness-H0-1` / `开始 Harness-H2-1` / `完成 Harness-H2-1`

> **蓝图原文（勿改）：** [Harness改造计划.md](./Harness改造计划.md)  
> **本文：** 按旧蓝图 H0～H7 **逐步跟做**的施工说明书（给人照着写代码用的）。  
> 另有精简执行版 [AgentRuntime改造计划.md](./AgentRuntime改造计划.md)；**以本文为准。**

### 怎么读这份计划（先看这里）

每个小任务都按同一套写法，避免只剩一行表格：

1. **人话** — 用大白话说这一步在干什么  
2. **痛点** — 现在代码哪里难受，为什么要改  
3. **做完后** — 你应该看到什么结果  
4. **建议文件** — 新建/改哪些路径  
5. **类与方法** — 每个方法：输入什么、干什么、给谁用  
6. **验收** — 怎样算过关（最好能跑一条命令）  
7. **不要做** — 本步边界，防止一次改爆

进度勾选在 **§2**；细则在 **§3**。一次只做一个编号。

---

## 0. 你要先建立的概念

```text
Harness / Runtime  = 套在所有 Agent 外的统一运行壳（Run、事件、策略、取消）
Executor           = 某个领域 Agent 的执行器（Chat / Knowledge / Alarm）
Registry           = 注册表：有哪些 Agent、Tool、Model、Policy
RunEvent           = 标准事件（JSON 与 SSE 都消费同一条流）
Checkpoint         = 可恢复的工作状态（尤其 Alarm），不是聊天记录
```

### 0.1 什么是一次 Run

**Run = 一次完整的 Agent 执行生命周期**（从接请求到终态），不是单独的 Python 类名。

| 名词 | 作用（一句话） |
|---|---|
| **Run** | 「这一单任务」本身（抽象概念） |
| `run_id` | 这一单的唯一单号（UUID 字符串） |
| `RunRequest` | 下单内容：用户输入、session、agent_id、options |
| `RunContext` | 执行工作台：单号 + 请求 + 消息/预算/截止时间等运行态 |
| `RunEvent` | 过程广播：开始了、出 token、调工具、结束了 |
| `RunResult` | 结单结果：succeeded/failed/cancelled + output/error |
| `AgentExecutor` | 真正干活的领域执行器（只认 Context，只吐 Event） |
| `AgentRuntime` | 统一开跑的门面：建 Run、转发事件、归一失败 |

一次调用的数据流：

```text
调用方（测试 / FastAPI）
    │  RunRequest
    ▼
AgentRuntime.execute_stream / execute
    │  生成 run_id，组装 RunContext
    │  yield run.started
    ▼
AgentExecutor.astream(ctx)
    │  yield model.* / tool.* / workflow.step / run.completed|failed
    ▼
调用方消费 RunEvent（SSE）或聚合为 RunResult（JSON）
```

原则（与蓝图一致）：

- **模块化单体**，不拆微服务。
- Chat 继续 LangGraph ReAct；Alarm 继续 Pipeline + Replan。
- JSON 与 SSE **同一执行链**（都走 Runtime，禁止两套业务 if）。
- 渐进迁移；旧 API 兼容；特性开关切流。
- CrewAI：**不下沉 Harness**（H4-5）；旧 `run` 可选遗留，默认关。

目标目录（最终态，中间可先只建 `harness/`）：

```text
app/harness/{contracts,runtime,registry,policies,observability,storage}
app/agents/{chat,knowledge,alarm}
app/integrations/   # 可后期再搬
app/api/            # 可后期再搬
```

H2 建议文件：

```text
app/harness/runtime/
  __init__.py          # 导出 AgentRuntime
  agent_runtime.py     # AgentRuntime 本体
  cancellation.py      # H2-4：取消令牌（可后补）
tests/test_agent_runtime.py
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

- [x] H2-1 `AgentRuntime.execute_stream`
- [x] H2-2 JSON 消费同一事件流
- [x] H2-3 FastAPI 降为 Transport Adapter（可先接 Fake/单 Agent）
- [x] H2-4 取消语义
- [x] H2-5 SSE 短事务边界（仅约定；完整改造延期）

### H3 Registry 与 Gateway

- [x] H3-1 Agent Registry
- [x] H3-2 Model Gateway（router/worker/judge）
- [x] H3-3 Tool Registry
- [x] H3-4 Tool Runner（校验/超时/类型化错误/事件）
- [x] H3-5 Policy Registry（先注册结构，策略可薄）

### H4 Agent 迁移

- [x] H4-1 ChatExecutor + 特性开关
- [x] H4-2 KnowledgeExecutor
- [x] H4-3 AlarmExecutor
- [x] H4-4 Router 抽出
- [x] H4-5 CrewAI：不下沉 Harness（遗留可选）

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

**阶段人话：** 先保证「换台机器也能装上、测得过、行为有对照」，再动架构。H0 **已完成**，下面留作回顾「当时每步在干什么」。

| 编号 | 人话（这一步在干什么） | 过关 |
|---|---|---|
| **H0-1** | 写清楚用 Python 几、怎么建环境 | 按文档能装起来 |
| **H0-2** | 依赖文件别坏编码、分层能 pip 装 | 本机/CI 能装 |
| **H0-3** | 配置字段和环境变量对齐；缺啥说人话 | 复制 example 能启动或明确缺项 |
| **H0-4** | PG/Milvus 要不要、缺了咋办写死 | 行为与文档一致 |
| **H0-5** | 离线测试全绿 + CI | pytest 离线子集绿 |
| **H0-6** | 冻几组黄金输入/输出，防止以后改歪 | 后续阶段可对照 |

原明细表（文件级）：

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

**阶段目标：** 所有 Agent 执行只从一个门面进出；JSON 与 SSE 消费同一条 `RunEvent` 流。  
**本阶段不做：** 真 Chat/Knowledge/Alarm 迁移（H4）、Registry（H3）、落库（H5）。

---

#### H2 角色分工（先建立分工再写代码）

| 角色 | 负责 | 不负责 |
|---|---|---|
| **调用方**（测试 / FastAPI Adapter） | 构造 `RunRequest`；消费事件或 `RunResult` | 不生成 `run_id`；不直接调 LangGraph |
| **`AgentRuntime`** | 建 Run、发 `run.started`、调 Executor、统一 sequence、捕获异常发 `run.failed`、（H2-2）聚合结果 | 不写闲聊/订单/RAG 业务 |
| **`AgentExecutor`** | 读 `RunContext`，产出业务相关 `RunEvent` | 不碰 HTTP；不自己分配全局 sequence（可由 Runtime 覆盖） |
| **Transport Adapter**（H2-3） | HTTP/SSE ↔ Runtime 的翻译 | 不做意图分支 / Agent if-else |

---

#### H2-1 `AgentRuntime` + `execute_stream`

**功能：** 实现「开一次 Run + 流式吐事件」的唯一执行面。  
**文件建议：** `app/harness/runtime/agent_runtime.py`  
**过关：** FakeExecutor 跑通；单测断言事件序与 sequence。

##### 类：`AgentRuntime`

| 成员 | 签名建议 | 做什么 | 作用 |
|---|---|---|---|
| `__init__` | `(self, executor: AgentExecutor)` | 保存 Executor 引用 | H2 先构造函数注入；H3 再换成从 Registry 按 `agent_id` 取 |
| `execute_stream` | `(self, request: RunRequest) -> AsyncIterator[RunEvent]` | **本阶段核心**：开 Run、转发事件流 | JSON/SSE/测试的共同入口 |
| `_apply_pre_policies` | `(self, ctx: RunContext) -> RunContext` | 薄前置钩子（可先原样返回 ctx） | 预留限流/预算/鉴权挂点，避免以后改主流程 |
| `_emit`（可选私有） | `(self, *, type, run_id, seq, payload=None) -> RunEvent` | 统一构造事件 | 少写重复字段，保证 sequence/run_id 一致 |

**刻意不要在本类出现：** FastAPI、`chat_graph`、DB Session、真实 LLM。

##### 方法详解：`execute_stream`

**一句话：** 把一次 `RunRequest` 变成有序的 `RunEvent` 流。

**必须按固定顺序做：**

| 步骤 | 代码意图 | 为什么 |
|---|---|---|
| 1. 校验 | 依赖 Pydantic；非法 `input` 直接让 ValidationError 冒泡或转 `run.failed`（二选一写进注释） | 脏请求不要进 Executor |
| 2. 建 Run | `run_id = str(uuid.uuid4())`；`ctx = RunContext(run_id=run_id, request=request)` | 一次执行一个单号；后续事件/日志都挂这个 id |
| 3. 前置策略 | `ctx = self._apply_pre_policies(ctx)`（可空实现） | 主流程稳定，策略可插拔 |
| 4. 发开始事件 | `yield RunEvent(type=RUN_STARTED, run_id=..., sequence=0)` | 调用方知道「跑起来了」 |
| 5. 调 Executor | `async for ev in self.executor.astream(ctx)` | **业务只在这里发生** |
| 6. 转发时归一 | 用**局部变量** `seq`，`yield ev.model_copy(update={"run_id": run_id, "sequence": seq})`；再 `seq += 1` | 禁止 `self.sequence`（并发会串号）；保证单调 0,1,2… |
| 7. 异常归一 | `except Exception` → `HarnessError.from_exception` → `yield RUN_FAILED`（payload=error.to_dict()） | 失败也是事件，JSON/SSE 都能收尾 |
| 8. 终态兜底（建议） | 若循环结束仍未见 `run.completed`/`run.failed`，Runtime 补一条 | 保证流一定有明确结束 |

**局部 `seq` 规则（写进注释）：**

- 每次进入 `execute_stream`：`seq = 0`
- Runtime 自己发的 `run.started` 用 `0`，然后 `seq = 1`
- 之后每转发/兜底一条事件用当前 `seq`，再 `+= 1`
- **不要**把 `seq` 存成实例字段

**异常映射约定：**

| 情况 | 应 yield | 不应 |
|---|---|---|
| Executor 抛任意 Exception | `run.failed`，带 category/message | `run.completed` |
| 调用方取消（H2-4） | 最终 `run.failed` 或 status=cancelled 的 completed 策略二选一，H2-4 定稿 | 静默断开无终态 |

##### FakeExecutor（单测专用，不是产品代码）

**做什么：** 实现 `async def astream(self, ctx) -> AsyncIterator[RunEvent]`，yield 少量假事件。  
**作用：** 不接 LLM 也能验证 Runtime 管道。  
**注意：** `AgentExecutor` 是 Protocol，**不能** `AgentExecutor()`；Fake **不要**继承 `AgentRuntime`。

```text
class FakeExecutor:
    async def astream(self, ctx: RunContext) -> AsyncIterator[RunEvent]:
        yield RunEvent(type=RUN_COMPLETED, run_id=ctx.run_id, sequence=999)  # sequence 可乱填，靠 Runtime 覆盖
```

##### 单测 `tests/test_agent_runtime.py` 最少覆盖

| 用例 | 断言 |
|---|---|
| 正常路径 | 首条 `run.started`；末条 `run.completed`；`sequence == [0,1,...,n-1]`；所有 `run_id` 相同 |
| Executor 抛错 | 出现 `run.failed`；不出现把失败标成 `run.completed` |
| 两次调用 | 第二次 sequence 仍从 0 开始（证明没用实例级计数器） |

---

#### H2-2 `execute`：JSON 消费同一事件流

**功能：** 非流式调用也走 `execute_stream`，最后聚合成一个 `RunResult`。  
**文件建议：** 仍在 `agent_runtime.py`  
**过关：** 无第二套「业务 if」；只根据事件类型聚合。

##### 方法：`execute`

| 项 | 说明 |
|---|---|
| **签名** | `async def execute(self, request: RunRequest) -> RunResult` |
| **做什么** | `async for ev in self.execute_stream(request)`，按事件更新内存中的结果草稿，返回最终 `RunResult` |
| **作用** | 给普通 JSON API 用；保证与 SSE **同一执行链** |

**聚合规则（建议写死在计划与代码注释）：**

| 见到的事件 | 对 `RunResult` 的影响 |
|---|---|
| `model.token` | 把 `payload.content` 追加到 `output`（或缓冲） |
| `run.completed` | `status=succeeded`；从 payload 取 `output`/`sources`/`usage`/`metadata`（若有） |
| `run.failed` | `status=failed`；`error` ← payload 或 HarnessError 字典 |
| 其它事件 | 可忽略，或写入 `metadata`/`usage` 计数 |

**禁止：** 在 `execute` 里再调一遍 Executor，或写 `if intent == ...`。

---

#### H2-3 Transport Adapter + 特性开关

**功能：** FastAPI 端点只做协议翻译，业务进 Runtime。  
**建议先改：** chat 相关一个端点（JSON 或 SSE 其一即可）。  
**过关：** 开关开 → Runtime；关 → 旧路径。

| 组件/函数 | 做什么 | 作用 |
|---|---|---|
| 请求解析函数 | HTTP body → `RunRequest` | 隔离 Pydantic/API schema 与 harness 契约 |
| SSE 适配器 | `async for ev in runtime.execute_stream(...)` → 写成 SSE 帧 | 前端流式体验 |
| JSON 适配器 | `result = await runtime.execute(...)` → 映射旧 `ChatResponse` 字段 | 旧客户端兼容 |
| 特性开关 | 如 `HARNESS_RUNTIME=1` 或 `HARNESS_CHAT=1` | 可回滚，降低切流风险 |

**端点内禁止出现：** 意图识别、选 Agent、直接 `chat_graph.ainvoke`（这些属 H4 / Router）。

H2-3 可先接 **FakeExecutor 或单一占位**，证明 Adapter 形状；真 Chat 迁移在 H4-1。

---

#### H2-4 取消语义

**功能：** 客户端断开后，尽快停止后续 model/tool。  
**文件建议：** `app/harness/runtime/cancellation.py` + Context 上挂信号。

| 符号/方法 | 做什么 | 作用 |
|---|---|---|
| `CancellationToken` 或 `asyncio.Event` | `cancel()` / `is_cancelled` / `wait` | 统一取消信号抽象 |
| 挂到 `RunContext` | 例如 `ctx.metadata["cancel"] = token`，或正式字段（H2 可加可选字段） | Executor 能读到 |
| Adapter 断开钩子 | FastAPI `Request.is_disconnected` / 生成器 `aclose` 时 `token.cancel()` | 把传输层断开翻译成 Run 取消 |
| Executor 约定 | 循环/工具调用前检查 cancel | 真正省钱、停副作用 |

**过关：** 单测里 cancel 后不再 yield 新业务事件；或手工断 SSE 验证。

---

#### H2-5 SSE 短事务边界

**功能：** 约定「流式响应期间不长持有同一个 DB AsyncSession」。  
**本轮实际做法（2026-09-22 决策）：**

- **先不改** `/api/v1/chat/stream` 行为（已确认：`Depends(get_db)` + `StreamingResponse` = 长持有）。
- 在 `AgentRuntime.execute_stream` 与 `chat_stream` 入口写清约定注释。
- **完整 SSE 改造延期**到 H4 `ChatExecutor` 能流式出 token 之后，单独做：
  1. 拆长生命周期 `get_db`
  2. Runtime SSE Adapter + 特性开关
  3. 断开 → `cancellation_token.cancel()`
- Redis 不纳入本轮；以后若上 Redis，可与短事务同一波，但 Redis **不能替代**拆 session。

**过关（本轮）：** 注释/计划约定到位即可。  
**过关（延期项）：** 见上「完整 SSE 改造」清单。

---

#### H2 任务勾选与过关表

| 编号 | 内容 | 过关 |
|---|---|---|
| **H2-1** | `AgentRuntime.execute_stream`：建 Run → 前置钩子 → 调 Executor → 归一 sequence → 失败变 `run.failed` | FakeExecutor 单测通过 |
| **H2-2** | `execute()` 只消费 `execute_stream` 聚合 `RunResult` | 无第二套业务分支 |
| **H2-3** | 一端点改为 Adapter + 特性开关 | 开关可切 Runtime / 旧路径 |
| **H2-4** | 取消令牌挂 Context；断开后停后续调用 | 单测或手工验证 |
| **H2-5** | SSE 不长持有 AsyncSession 的文档/注释约定 | 本轮：注释+延期记录；完整改造待 H4 后 |

### H3：Registry、模型与工具

**阶段人话：** H2 的 Runtime 还是「构造函数里塞一个 Executor」。这一步要变成：按名字查出 Agent / 工具 / 模型怎么用，并且**调工具、调模型都走统一入口**，方便打事件、超时、错误分类。

**本阶段仍可不接真实 Chat 全量流量**；用占位 Executor、包装现有 `get_llm`、注册现有订单/天气工具即可。

建议目录：

```text
app/harness/registry/
  agent_registry.py
  tool_registry.py
  policy_registry.py
app/harness/models/
  model_gateway.py
app/harness/tools/
  tool_runner.py
```

---

#### H3-1 `AgentRegistry` — 有哪些 Agent、怎么取出来

**人话：** 做一本 Agent 花名册。以后 Runtime 不写死 `ChatExecutor()`，而是 `registry.get("chat")` 拿到定义再跑。

**痛点：** 「跑哪个 Agent」散落在 `services/chat.py` 一类文件的 if/else 里，难测、难扩展。

**做完后：** 能登记一个 Chat 占位；能按 id 取回 Executor 等信息。

**建议文件：** `app/harness/registry/agent_registry.py`

**建议数据结构 `AgentDefinition`（dataclass 或 Pydantic 均可）：**

| 字段 | 含义 |
|---|---|
| `id` | 如 `"chat"` / `"knowledge"` / `"alarm"` |
| `version` | 实现版本，方便灰度 |
| `executor` | 实现了 `AgentExecutor` 的对象 |
| `prompt_version` | 提示词版本（字符串即可） |
| `tool_allowlist` | 允许用的工具名列表 |
| `model_roles` | 需要哪些模型角色，如 `{"worker": "default"}` |
| `policy_set` | 策略组合名，如 `"chat_default"` |

**类与方法（每个方法干什么）：**

| 方法 | 输入 | 干什么 | 谁调用 |
|---|---|---|---|
| `register(defn)` | 一份 `AgentDefinition` | 放进内存字典；重复 id 报错或覆盖（二选一写死） | 启动 lifespan / 测试 setup |
| `get(agent_id)` | 字符串 id | 取出定义；没有则抛清晰错误 | Runtime / Router |
| `list_ids()` | 无 | 列出已注册 id | 调试 / 看板 |
| `unregister(id)`（可选） | id | 测试用卸载 | 单测 |

**验收：** 单测 register → get；未知 id 有明确异常。  
**本步不要做：** 不要写业务逻辑；不要把注册表落到数据库（先内存）。

---

#### H3-2 `ModelGateway` — 统一找模型、调模型

**人话：** 把到处 `get_llm(...)` 收成一扇门。Executor 只说「我要 worker 角色、要流式」，Gateway 负责创建、（可选）重试和用量。

**痛点：** 模型创建分散；router/worker/judge 角色说不清；用量难统计。

**做完后：** 能按角色拿到可调用对象；流式或非流式至少一种能跑通（内部继续包现有 `get_llm` 完全可以）。

**建议文件：** `app/harness/models/model_gateway.py`

**角色先定三类：**

| 角色 | 典型用途 |
|---|---|
| `router` | 意图分类、轻量判断 |
| `worker` | 主对话 / 主生成 |
| `judge` | 可选质检、是否拒答 |

**类与方法：**

| 方法 | 干什么 | 作用 |
|---|---|---|
| `__init__(...)` | 读 Settings；按需缓存客户端 | 避免每次请求乱新建 |
| `get(role, **overrides)` | 按角色返回项目现有 LLM 类型 | Executor 不关心 API Key |
| `astream_text(role, messages, ...)`（可后补） | 流式吐文本 | 统一流式入口 |
| `ainvoke_structured(...)`（可后补） | 结构化输出 | Router / Alarm 分类 |
| `record_usage(...)`（可薄） | 累计 tokens | 给 Budget / `RunResult.usage` |

**验收：** 单测用 Fake/mock；`get("worker")` 不炸。  
**本步不要做：** 不要重写整套 Prompt；不要一次上完整 OpenTelemetry。

---

#### H3-3 `ToolRegistry` — 有哪些工具

**人话：** 工具花名册：名字 →（说明书 `ToolSpec` + 真正可调用的 handler）。

**痛点：** 工具和 Agent 绑死在 graph 节点里；新加工具往往要改 Executor 核心。

**做完后：** 至少注册现有订单/天气类工具；能按名取出 Spec + handler。

**建议文件：** `app/harness/registry/tool_registry.py`

登记时必须两样：

1. `ToolSpec` — 给模型/校验看的说明书（H1 已有）  
2. `handler` — 真正执行的可调用对象（sync/async 均可，Runner 里统一）

**类与方法：**

| 方法 | 干什么 |
|---|---|
| `register(spec, handler)` | 登记 |
| `get(name)` | 返回 `(spec, handler)` |
| `get_spec(name)` | 只取说明书 |
| `list_specs(allowlist=None)` | 按白名单过滤，供 Agent 绑定 |

**验收：** 注册后 list 按 allowlist 过滤正确。  
**本步不要做：** 不要在 Registry 里执行工具（执行是 ToolRunner 的事）。

---

#### H3-4 `ToolRunner` — 真正跑一把工具

**人话：** 谁要调工具都经我：权限、参数校验、超时、截断、脱敏、类型化错误。失败不再只靠 `"[TOOL_ERROR]..."` 字符串。

**痛点：** `chat_graph` 里散落调用；超时与错误不统一。

**做完后：** 有 `arun(name, args, ctx)`；成功/失败可映射成 `HarnessError` 或清晰结果对象。

**建议文件：** `app/harness/tools/tool_runner.py`

**`arun` 固定步骤（按顺序写）：**

1. 从 Registry 取 spec + handler；没有 → `HarnessError`  
2. 检查 Agent 白名单 / 权限是否允许该工具  
3. 按 `input_schema` 做最小校验（可先手写必填）  
4. `asyncio.wait_for(handler, timeout=spec.timeout_sec)`  
5. 结果过长则截断；敏感字段脱敏（可先做 1～2 个字段）  
6. 成功返回结果；失败映射为 `HarnessErrorCategory.TOOL` / `TIMEOUT` 等  

**事件谁打？** H3 建议：**Executor yield `tool.started/completed/failed`**，Runner 只负责执行与错误（更简单）。

**验收：** Fake handler 单测；超时、校验失败不进/中断 handler。  
**本步不要做：** 不要删光 chat_graph 旧调用（H4 再替换）。

---

#### H3-5 `PolicyRegistry` — 策略组合先挂上名字

**人话：** 「chat 用哪套限额/权限」先能查到一个组合；里面的策略实现可以很空，但**挂载点要在**，否则 H6 没地方插。

**建议文件：** `app/harness/registry/policy_registry.py` + 空壳 `app/harness/policies/base.py`

**类与方法：**

| 方法 | 干什么 |
|---|---|
| `register(name, policy_set)` | 登记一套策略 |
| `get(name)` | 取出 |
| `PolicySet.apply_before(ctx) -> ctx` | 前置；H3 可原样返回 ctx |
| `PolicySet.apply_after(ctx, result)`（可选） | 后置 |

**验收：** `AgentDefinition.policy_set` 能解析到对象；`apply_before` 不炸。  
**本步不要做：** 不要在 H3 实现完整 Budget/Auth（那是 H6）。

---

#### H3 过关清单

| 编号 | 怎样算过关 |
|---|---|
| H3-1 | 可注册/获取 Chat 占位 Agent |
| H3-2 | `get("worker")` 可用（真或 fake） |
| H3-3 | 现有工具可注册、可按白名单列出 |
| H3-4 | Runner：校验/超时/类型化错误单测通过 |
| H3-5 | 按名取到策略集；前置钩子可挂到 Runtime |

---

### H4：Agent 迁移

**阶段人话：** 把现有 Chat / Knowledge / Alarm **包成 Executor**，挂到 Registry；用特性开关切流量。旧 API 先留着，用黄金用例对照行为。

**总原则：** 一次只迁一个 Agent；开关必须能回滚；不要一天删光旧代码。

建议目录：

```text
app/agents/harness_chat/executor.py       # ChatExecutor（包装 chat_react/chat_graph）
app/agents/harness_knowledge/executor.py  # KnowledgeExecutor
app/agents/harness_alarm/executor.py      # AlarmExecutor（与旧 alarm/ 包并存）
app/harness/routing/router.py
```

> **命名约定：** Harness 新增执行器放在 `app/agents/harness_*` **目录**下（目录带 `harness_` 前缀），与既有 `chat_graph.py` / `chat_react.py` / `alarm/` 区分；旧文件不改名、不搬家。包内文件可用普通名 `executor.py`。

---

#### H4-1 `ChatExecutor` — 包装现有闲聊/工具循环

**人话：** 把现在的 LangGraph ReAct（`chat_graph` / `chat_react`）塞进 `astream(ctx)`：读用户输入，边跑边 yield `model.token` / `tool.*`，最后 `run.completed`。

**痛点：** 业务堆在 service 层，和 Runtime 标准事件对不上。

**文件建议：** `app/agents/harness_chat/executor.py`（类名 `ChatExecutor`）

| 方法 | 干什么 |
|---|---|
| `__init__(...)` | 注入 ModelGateway / ToolRunner（初期仍可调旧函数） |
| `astream(ctx)` | 驱动现有 graph；把内部流式 chunk **翻译**成 `RunEvent` |
| `_map_chunk_to_events`（建议私有） | 集中「旧事件 → 标准事件」，避免 astream 里一堆 if |

**开关建议：** 继续用现有 `HARNESS_RUNTIME`（或另加 `HARNESS_CHAT`）：开 → Runtime + `ChatExecutor`；关 → 旧 `services.chat.run`。Echo 换成真 `ChatExecutor`，**不要删**开关与旧分支。

**验收：** 闲聊 / 订单 / 天气 / 工具失败 / 流式 token；对照 `tests/golden/chat.json`；开关关时旧路径仍可用。  
**本步不要做：** 不要顺手重写 ReAct 算法；不要强行全量切、去掉回滚开关。

---

#### H4-2 `KnowledgeExecutor` — RAG 问答

**人话：** 检索继续用 `app/rag`；外面加 Executor：检索 → 生成 → 带 `sources` 的完成事件。

**文件建议：** `app/agents/harness_knowledge/executor.py`

**类与方法：**

| 方法 | 干什么 |
|---|---|
| `astream(ctx)` | 跑检索+生成；可对 retrieve/generate yield `workflow.step`，再吐 token |
| （可选）检索工具化 | 把 retriever 注册进 ToolRegistry |

**验收：** 有来源、无答案约束、流式；对照 knowledge 黄金用例。  
**本步不要做：** 不要换向量库。

---

#### H4-3 `AlarmExecutor` — Pipeline + Replan

**人话：** 告警流水线逻辑保留；每一步边界打成 `workflow.step`；补页 / 换 playbook / 跳过要在事件里能看出来。

**文件建议：** `app/agents/harness_alarm/executor.py`

**类与方法：**

| 方法 | 干什么 |
|---|---|
| `astream(ctx)` | 驱动现有 alarm pipeline；步骤边界 yield `workflow.step` |
| 内部 replan | 保持现有策略，只补事件与 `HarnessError` 分类 |

**验收：** 对照 alarm 黄金用例；外部依赖失败有明确失败事件。  
**本步不要做：** 不要把 Alarm 改成纯 ReAct。

---

#### H4-4 Router — 从 Chat Service 抽出「去哪个 Agent」

**人话：** 「这句话是闲聊还是告警」现在藏在 `chat.py`。抽成独立模块：文本 → `agent_id`，并让上层发 `route.selected`。

**类与方法：**

| 方法 / 类型 | 干什么 |
|---|---|
| `classify(input, ...) -> RouteDecision` | 返回该去哪个 Agent |
| `RouteDecision` | 至少含 `agent_id`、`reason`；可选分数 |

**谁调用：** Adapter 或 Runtime 前置。Executor **自己不要再路由一遍**。

**验收：** 若干句子单测；`RunRequest.agent_id` 已填则可跳过路由；有回退旧逻辑的开关。  
**本步不要做：** 不要上复杂多 Agent 辩论。

---

#### H4-5 CrewAI：做成插件，或正式下线（必须二选一）

**人话：** 主路径不能长期「Crew 一套、Graph 一套」还测不干净。要么注册成默认关闭的第四 Executor，要么文档写明废弃 + 默认走主路径。

**决策（2026-09-23）：不下沉到 Harness。**

- Harness 只注册 `chat` / `knowledge` / `alarm`，**不**增加 `CrewExecutor`。
- 主路径：`HARNESS_RUNTIME` → Router → 上述三个 Executor。
- `app/agents/crew.py` + `USE_CREW` 仅作为**旧 `services.chat.run` 上的可选遗留**（默认 `false`）；不作为 Harness 能力，不进 `AgentRegistry`。
- 后续若物理删除 Crew，另开任务；本步只定边界。

**验收：** 本计划 + README 写明决策；默认 `USE_CREW=false` 可离线测；Registry 无 crew。  
**本步不要做：** 不要把 Crew 包进 `harness_*`；不要「先留着以后再说」又不写决策。

---

#### H4 过关清单

| 编号 | 怎样算过关 |
|---|---|
| H4-1 | 开关切 Chat；黄金用例等价 |
| H4-2 | Knowledge 来源/无答案/流式 OK |
| H4-3 | Alarm 步骤事件 + 关键路径 OK |
| H4-4 | Router 可单测、可回退 |
| H4-5 | 决策：Crew 不下沉 Harness；文档已写明 |

---

### H5：状态、存储与恢复

**阶段人话：** 跑过的 Run 要能查；Alarm 中断后能从安全点接着跑；大报告存元数据；关键事件可回放。存储先用 **PostgreSQL**，别一上来上消息队列。

建议目录：

```text
app/harness/storage/
  run_repository.py
  checkpoint_repository.py
  artifact_repository.py
  event_repository.py
```

---

#### H5-1 Run 表与仓储

**人话：** 每次 Runtime 执行，留一条「跑过什么」的台账。

**建议字段：** `run_id`, `agent_id`, `session_id`, `status`, `input`, `output`, `error`, `usage`, `started_at`, `ended_at`, `agent_version`

**方法：**

| 方法 | 干什么 | 何时调用 |
|---|---|---|
| `create_run(...)` | 插入一条 | Run 开始（短事务） |
| `update_run(...)` | 更新终态/输出/错误/用量 | Run 结束 |
| `get_run(run_id)` | 查询 | 运维 / 回放 |
| `list_runs(session_id=...)` | 列表（可选） | 会话页 |

**注意：** 遵守 H2-5，不要把整个 SSE 包在同一个 DB Session 里。

**验收：** FakeExecutor 跑一次，库里能查到。  
**本步不要做：** 不要把超大 messages 无裁剪塞进一行。

---

#### H5-2 Checkpoint 接口 + PG JSONB

**人话：** Checkpoint = 工作进度快照（尤其 Alarm），**不是**聊天记录。

**方法：**

| 方法 | 干什么 |
|---|---|
| `save(run_id, name, payload: dict)` | 写入/覆盖 |
| `load(run_id, name)` | 读取，没有则 None |
| `list(run_id)` | 列出该 Run 检查点 |

**验收：** 读写一轮测试通过。  
**本步不要做：** 不要用 Checkpoint 存密码明文。

---

#### H5-3 Artifact 元数据

**人话：** 报告、抓取结果等大家伙：库里只存元数据（路径、类型、大小、归属 run），文件放磁盘或对象存储。

**方法：** `register_artifact(...)` / `get_artifact(id)` / `list_by_run(run_id)`

**验收：** 告警报告能关联到 `run_id`。  
**本步不要做：** 不要把数兆 HTML 塞进 PG 一行。

---

#### H5-4 关键 `RunEvent` 落库

**人话：** 把过滤后的标准事件按序存下，按 `run_id` 能回放。

**方法：** `append_event(ev)` / `list_events(run_id)`

**注意：** `visibility=internal` 是否入库要有策略；写入前脱敏（与 H6 衔接）。

**验收：** 一次 Run 后，库中事件与内存关键事件一致（允许过滤后的子集）。

---

#### H5-5 Alarm 恢复：幂等键 + 只从可恢复步骤继续

**人话：** 进程挂了再起来，只能从「声明可恢复」的步骤接着干；已经做过的外部操作靠幂等键防止再做一次。

**Checkpoint 里至少要能恢复：** 已抓取页、摘要、当前 playbook、replan 次数、已完成步骤、外部操作幂等键。

**流程：**

| 时机 | 干什么 |
|---|---|
| 运行中 | 每完成可恢复步骤就 `save` |
| 再次启动 | `astream` 发现 checkpoint → 跳过已完成步骤 |
| 工具写操作 | 带幂等键；重复调用无第二次副作用 |

**验收：** 专门恢复测试：中断 → 重启 → 不重复危险外部操作。  
**本步不要做：** 不要从任意半步瞎恢复。

---

#### H5 过关清单

| 编号 | 怎样算过关 |
|---|---|
| H5-1 | Run 可查 |
| H5-2 | Checkpoint 可读写 |
| H5-3 | Artifact 可关联报告 |
| H5-4 | 按 run_id 回放事件 |
| H5-5 | Alarm 恢复测试通过 |

---

### H6：策略与可观测性

**阶段人话：** 把「能不能跑、跑多少、坏了重不重试、日志能不能出现密钥」收成策略，挂进 Runtime；看板和 SSE **只认标准 `RunEvent`**。

建议目录：

```text
app/harness/policies/
  auth.py budget.py retry.py timeout.py cache.py data.py tool_policy.py
  chain.py
app/harness/observability/
  trace.py
  redact.py
```

---

#### H6-1 七类策略（每类先做最小可用）

**人话：** 一个策略一个小类，先能挡住最常见的坏事。

| 策略 | 人话职责 | 最小可用 | 关键方法 |
|---|---|---|---|
| AuthPolicy | 有没有权跑这个 Agent/工具 | caller + allowlist | `check(ctx)`，不行就 raise |
| BudgetPolicy | 别无限刷模型/工具 | `max_tool_calls` / `max_tokens` | 调用前检查计数 |
| RetryPolicy | 哪些错误值得重试 | 仅 timeout/网络；写操作看 idempotent | `should_retry(err, attempt)` |
| TimeoutPolicy | 分层超时 | Run / model / tool 三层秒数 | 提供秒数或 deadline |
| CachePolicy | 什么可缓存 | 可先 no-op | `get/set`；key 含版本、不含敏感 |
| DataPolicy | 日志脱敏 | Token/密码/手机号打码 | `redact(obj)` |
| ToolPolicy | 工具参数与目标限制 | 白名单 + 简单范围 | `check_call(name, args, ctx)` |

**验收：** 每类至少 1～2 个单测。

---

#### H6-2 `PolicyChain` 挂进 Runtime

**人话：** Runtime 不要写七个 if；只调 Chain 的 before/after。

| 方法 | 何时 | 干什么 |
|---|---|---|
| `before_run(ctx) -> ctx` | `execute_stream` 开头 | Auth、Budget 初始化、Deadline |
| `before_model` / `before_tool`（可选） | Gateway / Runner 内 | 限额检查 |
| `after_run(ctx, result)` | 结束 | 审计、缓存 |

超预算/超时必须变成标准错误事件（`HarnessError` + `run.failed` / `tool.failed`），不能只打日志。

**验收：** 把 budget 设极小，Fake 跑一通能收到 policy/timeout 类失败。

---

#### H6-3 Dashboard / SSE 只消费标准事件

**人话：** 前端不要再把各 Agent 私有 stage 字典当唯一真相；统一映射到 `EVENT_TYPES`。

**要做的事：**

1. 列一张「旧事件名 → 标准 type」表  
2. SSE Adapter 只转发 `RunEvent`  
3. Dashboard 读同一词表（可短暂双读，最终删私有）

**验收：** 关键进度不依赖私有字典也能显示。  
**本步不要做：** 不要为看板发明第三套事件。

---

#### H6-4 脱敏与审计

**人话：** Trace/日志不能出现 API Key、密码等；审计能回答「谁在何时调了什么工具」。

| 方法 / 字段 | 干什么 |
|---|---|
| `redact_event` / `redact_dict` | 写出前打码 |
| 审计字段 | `run_id`, `caller`, `agent_id`, `tool_name`, `status`, `latency_ms`（不含敏感正文） |

**验收：** 单测喂含 `sk-` / password 的 payload，落库或日志字符串不再明文出现。

---

#### H6 过关清单

| 编号 | 怎样算过关 |
|---|---|
| H6-1 | 策略单测覆盖关键分支 |
| H6-2 | Chain 挂上；超限有标准错误事件 |
| H6-3 | Dashboard/SSE 主路径认标准事件 |
| H6-4 | 脱敏单测通过 |

---

### H7：评测与扩展验证

**阶段人话：** 证明这套壳可测、可回归、可扩展：测试分层清楚；和现有 `eval/` 对齐；最后用一个新 Agent 证明「只注册、不改 Runtime」。

---

#### H7-1 测试分层补齐

**人话：** 不同测试干不同的事，别混成一个巨型文件。

| 层 | 测什么 | 人话 |
|---|---|---|
| Contract | 契约形状、事件名、协议 | 接口有没有按说明书来 |
| Unit | Router、Policy、错误映射、sequence | 小零件对不对 |
| Golden | 固定输入 → 关键输出/轨迹 | 别行为漂移 |
| Replay | 用录好的模型/工具响应重放 | 不花真钱回归 |
| Failure | 超时、依赖挂、取消 | 坏的时候是否体面失败 |

**验收：** CI 离线层绿；至少有模型超时、工具失败各一例失败注入。

---

#### H7-2 与现有 `eval/` 对齐

**人话：** 指标名别另起炉灶；RAG、路由、工具选择、Alarm 结论等，能挂现有评测就挂。

**要做的事：** 写清「哪个脚本测哪个 Agent」；留一份可重复跑的基线命令和结果（markdown 即可）。

**验收：** 有人按文档能跑出基线数字或报告。

---

#### H7-3 示例新 Agent（扩展大考）

**人话：** 新增 `echo` 或 `summary` 玩具 Agent——**只加** Definition + Executor + `register`，**禁止**改 `AgentRuntime`、禁止改 API 框架、禁止改旧 Agent 来「迁就」它。

**建议步骤：**

1. 写 `EchoExecutor.astream`：把 input 放进 `run.completed`  
2. `AgentRegistry.register(...)`  
3. 用 Runtime 跑通（可用 `agent_id=echo` 强制）

**验收：** Diff 里看不到「为了 echo 去改 Runtime/旧 Agent」。  
**本步不要做：** 不要借机重构全仓库目录。

---

#### H7 过关清单

| 编号 | 怎样算过关 |
|---|---|
| H7-1 | 分层测试 + CI 离线绿 |
| H7-2 | eval 基线可跑可查 |
| H7-3 | 新 Agent 只注册不改 Runtime |

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

1. 一次只做 **一个编号**（如 H2-1），做完打勾并说 `完成 Harness-H2-1`。  
2. 助手讲解或你自己写代码时，对照该编号下的：**人话 → 痛点 → 方法表 → 验收 → 不要做**。  
3. 行为是否漂移，用 H0-6 黄金用例回归。  
4. 大搬家（`integrations/`、`api/`）放在 H4 稳定之后，避免早期大扩散。  
5. 计划写得让人看不懂时，优先改计划，不要硬猜着写代码。

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
| 2026-09-22 | 扩充 H2 计划：Run 概念、角色分工、各方法「做什么/作用」、execute_stream 步骤表、聚合/取消/Adapter 约定 |
| 2026-09-22 | 按「人话/痛点/方法/验收/不要做」模板补全 H3～H7；文首增加怎么读 |
| 2026-09-22 | **完成 H2-1**：`AgentRuntime.execute_stream` + `tests/test_agent_runtime.py`（4 passed） |
| 2026-09-22 | **完成 H2-2**：`execute()` 聚合 RunResult；单测 7 passed |
| 2026-09-22 | **完成 H2-3**：`adapter/chat_http.py` + `HARNESS_RUNTIME` 开关；Echo 占位；adapter 单测 |
| 2026-09-22 | **完成 H2-4**：取消令牌 + Runtime 检查；破环依赖；`tests/test_cancellation.py`（23 相关测全绿） |
| 2026-09-22 | **完成 H2-5（约定）**：注释固化短事务；完整 SSE 改造延期至 H4 后；**H2 里程碑约定层收口** |
| 2026-09-23 | **完成 H3-1**：`AgentRegistry` + `AgentDefinition` + `tests/test_agent_registry.py` |
| 2026-09-23 | **完成 H3-2**：`ModelGateway`（角色映射/缓存/用量薄记账）+ `tests/test_model_gateway.py` |
| 2026-09-23 | 开始引导 **H3-3 Tool Registry** |
| 2026-09-23 | **完成 H3-3**：`ToolRegistry` + `register_builtin_tools`（order/weather）+ 单测 |
| 2026-09-23 | **完成 H3-4**：`ToolRunner.arun`（校验/白名单/超时/截断/HarnessError）+ 单测 7 passed |
| 2026-09-23 | **完成 H3-5**：PolicySet/PolicyRegistry + 默认策略 + Runtime 前置钩子；**H3 收口** |
| 2026-09-23 | H4 曾拟「全量无开关」；**已改回**：保留 `HARNESS_RUNTIME` 双轨，开→ChatExecutor，关→旧 `run` |
| 2026-09-23 | **完成 H4-1**：`harness_chat/executor.py` + adapter 传入 kb/db；开关保留；adapter/executor 单测 |
| 2026-09-23 | **完成 H4-2**：`KnowledgeExecutor` + `knowledge_http` + `/retrieval` 开关；`RunResult.sources` 允许 str；单测 |
| 2026-09-23 | **完成 H4-3（Executor）**：`harness_alarm/executor.py` 包装 `run_alarm_agent`；单测 2 passed；HTTP 接线待做 |
| 2026-09-23 | **完成 H4-3 HTTP**：`alarm_http` + `/api/v1/alarm` 开关；adapter 单测 |
| 2026-09-23 | **完成 H4-4（模块）**：`harness/routing` + `classify`；复用 is_alarm/classify_intent；单测；Adapter 接入待做 |
| 2026-09-23 | **H4-4 接入 Chat Adapter**：`chat_harness_http` 先 classify 再填 `agent_id`/`options.route`；单测 mock 路由 |
| 2026-09-23 | **H4-4 分发**：`register_builtin_agents` + `build_chat_runtime(agent_id)` 选 Executor；未知回退 chat；分发单测 |
| 2026-09-23 | **H4-5 决策**：CrewAI **不下沉** Harness；Registry 仅 chat/knowledge/alarm；Crew 为旧 `run` 可选遗留（默认关） |