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

- [ ] H1-1 `RunRequest`
- [ ] H1-2 `RunContext`
- [ ] H1-3 `RunEvent`
- [ ] H1-4 `RunResult`
- [ ] H1-5 `AgentExecutor` 协议
- [ ] H1-6 `ToolSpec`
- [ ] H1-7 `HarnessError` + 事件类型常量
- [ ] H1-T 契约单测

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

| 编号 | 内容 | 过关 |
|---|---|---|
| **H1-1** | `RunRequest`：`agent_id`、input、`session_id`、caller、options | 可序列化/校验 |
| **H1-2** | `RunContext`：`run_id`、`trace_id`、消息、权限、deadline、预算、metadata | 运行态不进 Registry |
| **H1-3** | `RunEvent`：type、timestamp、run_id、sequence、payload、visibility | 含约定事件名常量 |
| **H1-4** | `RunResult`：status、output、sources、artifacts、usage、error、metadata | 与旧 chat 响应可映射 |
| **H1-5** | `AgentExecutor`：`astream(ctx) -> AsyncIterator[RunEvent]`；取消约定 | Protocol + 文档字符串 |
| **H1-6** | `ToolSpec`：schema、权限、超时、重试、幂等 | 能描述现有 tool |
| **H1-7** | `HarnessError` 分类枚举 | validation/model/tool/policy/timeout/storage/internal |
| **H1-T** | `tests/test_harness_contracts.py` | 构造/校验/事件枚举单测通过 |

统一事件名：`run.started`、`route.selected`、`model.started`、`model.token`、`model.completed`、`tool.started`、`tool.completed`、`tool.failed`、`workflow.step`、`run.completed`、`run.failed`。

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
