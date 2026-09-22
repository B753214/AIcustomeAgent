# Agent Harness 改造计划

## 1. 改造目标

将当前智能运维 Agent 应用改造成“模块化单体 Harness + 可插拔领域 Agent”。Harness 统一管理 Agent 的运行上下文、执行生命周期、模型与工具调用、事件流、持久化、策略和观测；Chat、Knowledge/RAG、Alarm 保留各自适合的执行方式。

本次改造遵循以下原则：

- 不重新实现 LangGraph；Chat Agent 继续使用 LangGraph ReAct。
- Alarm 保留确定性 Pipeline + Replan，不强制改成 ReAct。
- RAG 拆分为可复用检索能力和 Knowledge Agent。
- JSON 与 SSE 使用同一条执行链路，避免业务逻辑分叉。
- 先在当前仓库内完成模块化，不急于发布独立 Python 包。
- 采用渐进迁移，旧接口和返回结构在迁移期保持兼容。

## 2. 目标架构

```text
FastAPI / CLI / Scheduler
          |
          v
      AgentRuntime
  Context / Event / Policy
          |
     Agent Registry
    /       |        \
 Chat   Knowledge    Alarm
 ReAct   RAG Flow   Plan/Replan
    \       |        /
       Tool Registry
          |
 Local / HTTP / MCP / Browser / Storage
```

建议的逻辑目录：

```text
app/
├── harness/
│   ├── contracts/       # Run、Agent、Tool、Event、Error 契约
│   ├── runtime/         # 生命周期、执行、取消、预算
│   ├── registry/        # Agent、Tool、Model 注册
│   ├── policies/        # 重试、超时、权限、限额、缓存
│   ├── observability/   # Trace、Metrics、审计
│   └── storage/         # 会话、Run、Checkpoint 仓储接口
├── agents/
│   ├── chat/            # LangGraph ReAct Executor
│   ├── knowledge/       # RAG Executor
│   └── alarm/           # Pipeline + Replan Executor
├── integrations/        # PostgreSQL、Milvus、MCP、天气、浏览器
└── api/                 # FastAPI Route、JSON/SSE Adapter
```

## 3. 总体计划表

| 阶段 | 名称 | 建议周期 | 核心工作 | 主要交付物 | 完成标准 |
|---|---|---:|---|---|---|
| H0 | 基线稳定 | 2～3 天 | 修复环境、配置、依赖和 CI；冻结现有行为 | 可复现环境、基线测试报告、API 契约快照 | Conda/Python 3.12 与 CI 均能跑完离线测试 |
| H1 | 核心契约 | 3～4 天 | 定义 Run、Context、Result、Event、Error、Executor 契约 | `harness/contracts/`、契约单测 | 现有三类 Agent 可通过适配器返回统一结果和事件 |
| H2 | Runtime 门面 | 4～6 天 | 建立统一生命周期；合并 JSON/SSE 执行逻辑 | `AgentRuntime`、API Adapter、运行时测试 | 同一请求的 JSON 与 SSE 最终结果一致 |
| H3 | Registry 与 Gateway | 4～6 天 | Agent/Tool/Model 注册；统一模型和工具调用 | 三类 Registry、Model Gateway、Tool Runner | 新工具无需修改 Runtime；所有调用有事件和类型化错误 |
| H4 | Agent 迁移 | 7～10 天 | 依次迁移 Chat、Knowledge、Alarm | 三个 Executor、兼容层、回归报告 | 旧接口不变，黄金用例与旧实现结果等价 |
| H5 | 状态与恢复 | 5～7 天 | Run、Checkpoint、Artifact 持久化；Alarm 断点恢复 | 仓储接口、PG 实现、恢复测试 | Alarm 可从安全步骤恢复，不重复已完成的外部操作 |
| H6 | 策略与观测 | 5～7 天 | 权限、预算、超时、缓存、审计、指标统一 | Policy Chain、统一 Trace、Dashboard Adapter | 每次模型/工具/步骤调用均可追踪且敏感字段已脱敏 |
| H7 | 评测与扩展验证 | 3～5 天 | 轨迹评测、回放、故障注入；接入一个示例 Agent | Eval Harness、回放工具、扩展示例 | 不修改 Runtime 即可注册并运行新 Agent |

按一人全职估算，总周期约 5～7 周。H3 的 Model Gateway 和 Tool Registry 可在契约确定后并行推进。

## 4. 分阶段任务

### H0：基线稳定

| 编号 | 任务 | 交付物 | 验收方式 |
|---|---|---|---|
| H0-1 | 统一支持的 Python 版本与 Conda 环境说明 | 环境文档、锁定的版本范围 | 新环境可按文档一次安装成功 |
| H0-2 | 将依赖文件统一为 UTF-8 并验证核心/开发/可选依赖 | 可安装的 requirements 文件 | `pip install -r` 在本机和 CI 成功 |
| H0-3 | 统一 Settings 字段和环境变量命名 | 完整 `.env.example`、配置校验表 | 复制示例配置后可启动或得到明确缺项提示 |
| H0-4 | 明确 PostgreSQL、Milvus 是否必选及降级语义 | 启动策略说明、健康检查约定 | 依赖缺失时行为与 README 一致 |
| H0-5 | 修正 CI 分支并运行全部离线测试 | CI 工作流、测试基线 | 语法检查和全部离线测试通过 |
| H0-6 | 固化 Chat、RAG、Alarm 黄金场景 | 输入/事件/结果快照 | 后续每阶段均可对照回归 |

### H1：核心契约

| 编号 | 契约 | 必备字段或职责 |
|---|---|---|
| H1-1 | `RunRequest` | `agent_id`、input、`session_id`、caller、options |
| H1-2 | `RunContext` | `run_id`、`trace_id`、消息、权限、deadline、预算、metadata |
| H1-3 | `RunEvent` | type、timestamp、run_id、sequence、payload、visibility |
| H1-4 | `RunResult` | status、output、sources、artifacts、usage、error、metadata |
| H1-5 | `AgentExecutor` | 统一事件流执行接口、取消语义和最终结果约定 |
| H1-6 | `ToolSpec` | 名称、版本、输入输出 Schema、权限、超时、重试、幂等性 |
| H1-7 | `HarnessError` | validation、model、tool、policy、timeout、storage、internal 分类 |

统一事件至少包含：`run.started`、`route.selected`、`model.started`、`model.token`、`model.completed`、`tool.started`、`tool.completed`、`tool.failed`、`workflow.step`、`run.completed`、`run.failed`。

### H2：Runtime 门面

标准生命周期：

1. 校验输入、调用身份和 Agent 权限。
2. 创建 Run，加载会话、Agent 定义和运行配置。
3. 执行限流、缓存、预算等前置策略。
4. 调用 Agent Executor 并转发标准事件。
5. 执行超时、取消、重试和错误归一化。
6. 保存消息、Run、Checkpoint、产物与审计记录。
7. 执行输出策略，产生 `RunResult`。

| 编号 | 任务 | 验收标准 |
|---|---|---|
| H2-1 | 实现 `AgentRuntime.execute_stream()` | 所有 Agent 都能产生标准事件流 |
| H2-2 | 非流式接口消费同一事件流并收集结果 | 不再维护独立 JSON 业务分支 |
| H2-3 | FastAPI 端点降为 Transport Adapter | Route 中不出现意图和 Agent 分支逻辑 |
| H2-4 | 实现客户端断开与主动取消 | 取消后停止后续模型和工具调用 |
| H2-5 | 定义流式事务边界 | SSE 期间不长期占用请求数据库事务 |

### H3：Registry、模型与工具

| 子系统 | 设计要求 |
|---|---|
| Agent Registry | 注册 `id`、版本、Executor、Prompt 版本、工具白名单、模型角色和策略集 |
| Model Gateway | 集中创建模型，支持 router/worker/judge 角色、结构化输出、流式、重试和用量统计 |
| Tool Registry | 统一注册本地函数、HTTP、MCP、浏览器及 RAG 工具 |
| Tool Runner | 参数校验、权限、超时、重试、结果截断、脱敏、错误映射和事件上报 |
| Policy Registry | 按 Agent、调用方和环境组合权限、预算、缓存及可靠性策略 |

工具失败不能再依赖字符串前缀作为唯一判断依据；内部使用类型化结果，只有面向模型时才转换为明确的 ToolMessage。

### H4：Agent 迁移

| 顺序 | Agent | 迁移策略 | 保留内容 | 重点验收 |
|---:|---|---|---|---|
| 1 | Chat | 将现有 LangGraph 包装为 `ChatExecutor` | 工具循环、失败次数、递归上限 | 普通聊天、订单、天气、工具失败和流式 Token |
| 2 | Knowledge | 拆分 Retriever Tool 与 `KnowledgeExecutor` | BM25、向量检索、RRF、重排、引用 | 检索结果、来源、无答案约束和流式生成 |
| 3 | Alarm | 将 Pipeline 包装为 `AlarmExecutor` | Parse、Classify、Fetch、Analyze、Replan、Report | 补页、换 Playbook、跳过、外部依赖失败 |
| 4 | Router | 从 Chat Service 中抽出路由策略 | 启发式直达告警、结构化意图分类 | 路由错误可观测、可回退、可评测 |
| 5 | CrewAI | 作为可选 Executor 插件接入或下线 | 仅保留有差异价值的能力 | 不得与主路径形成不可测试的重复实现 |

迁移期间保留兼容 Adapter，通过特性开关按 Agent 切换新旧路径；不要一次性整体替换。

### H5：状态、存储与恢复

| 状态类型 | 内容 | 推荐存储 |
|---|---|---|
| Session Memory | 用户与助手消息、摘要、会话元数据 | PostgreSQL |
| Run | 输入、状态、Agent 版本、开始结束时间、错误、用量 | PostgreSQL |
| Checkpoint | 当前节点、工作状态、下一步、重试次数 | PostgreSQL JSONB |
| Artifact | 报告、抓取结果、较大中间产物 | 数据库元数据 + 对象/文件存储 |
| Trace Event | 标准运行事件、耗时、关联 ID | 初期 PostgreSQL，后续可接 OpenTelemetry |

Alarm checkpoint 至少保存已抓取页、监控数据摘要、Playbook、Replan 次数、已完成步骤和外部操作幂等键。恢复时只能从声明为可恢复的步骤继续。

### H6：策略与可观测性

| 策略 | 关键要求 |
|---|---|
| Auth Policy | Agent 和工具级权限；会话与调用方绑定 |
| Budget Policy | 最大模型轮次、工具调用次数、Token、耗时和费用 |
| Retry Policy | 只重试明确的瞬时错误；写操作要求幂等 |
| Timeout Policy | Run、模型、工具、工作流步骤分层超时 |
| Cache Policy | 缓存键包含 Agent/Prompt/模型/知识库版本，排除敏感或时效数据 |
| Data Policy | Prompt、工具参数、Trace 和错误信息按字段脱敏 |
| Tool Policy | 工具白名单、参数范围、网络目标和浏览器操作限制 |

Dashboard 和 SSE 只消费标准事件，不再理解每个 Agent 的私有事件字典。进程内 Trace 可保留为开发 Adapter，生产环境需要持久化或接入 OpenTelemetry。

### H7：评测与扩展验证

| 测试层 | 覆盖内容 |
|---|---|
| Contract Test | 每个 Agent、Tool、Storage Adapter 是否遵守统一契约 |
| Unit Test | 路由、策略、状态转换、错误映射、事件顺序 |
| Golden Test | 固定输入对应的工具轨迹、来源、最终状态和关键输出 |
| Replay Test | 使用保存的模型/工具响应离线重放一次 Run |
| Failure Test | 模型超时、MCP 断开、Milvus 不可达、数据库回滚、浏览器失败 |
| Eval | RAG 命中与忠实度、路由准确率、工具选择率、Alarm 结论完整度 |

最终用一个简单的新 Agent 做扩展验收：只增加 Agent 定义、Executor 和注册代码，不允许修改 Runtime、API 或已有 Agent。

## 5. 关键验收指标

| 维度 | 指标 |
|---|---|
| 一致性 | JSON 与 SSE 的最终输出、来源、错误和 Trace 一致 |
| 扩展性 | 新增 Agent 不修改 Runtime；新增工具不修改 Executor 核心 |
| 可靠性 | 每次外部调用均有超时、错误分类和可配置重试 |
| 可恢复性 | Alarm 在进程重启后可从安全 checkpoint 继续 |
| 可观测性 | 模型、工具和步骤均有 run_id、耗时、状态和关联事件 |
| 安全性 | 工具权限可控；Trace 不泄露 Token、密码或敏感正文 |
| 可测试性 | 核心离线测试不依赖真实 LLM、PG、Milvus、MCP 或浏览器 |
| 兼容性 | 现有 `/api/v1/chat`、stream、ingest 和 analyze 契约保持兼容 |

## 6. 主要风险与控制措施

| 风险 | 表现 | 控制措施 |
|---|---|---|
| 过度抽象 | 为未知场景设计大量基类和配置 | 只抽取三个现有 Agent 已重复的能力 |
| 行为漂移 | 新旧路径回答、事件或工具选择不同 | 黄金测试、双轨运行、逐 Agent 切换 |
| 流式复杂度 | Token、工具事件、事务和取消互相影响 | 事件流作为唯一执行接口，明确事务和取消边界 |
| 全局状态污染 | Tool、KB、缓存跨请求串扰 | Registry 只保存定义，运行状态进入 `RunContext` |
| 外部操作重复 | 恢复或重试导致重复抓取、写入或登录 | 工具声明幂等性，checkpoint 保存幂等键 |
| 多框架重复 | CrewAI 与 LangGraph 长期维护两套逻辑 | CrewAI 仅作为插件；无独特价值则逐步下线 |
| 存储耦合 | AsyncSession 跨线程或长 SSE 生命周期传播 | Repository 接口和短事务，运行时显式控制作用域 |

## 7. 建议里程碑

| 里程碑 | 包含阶段 | 可演示成果 |
|---|---|---|
| M1：可复现基线 | H0 | 新环境和 CI 可以稳定安装、启动、测试 |
| M2：Harness 骨架 | H1～H2 | 同一 Runtime 同时支持 JSON 和 SSE |
| M3：可插拔运行 | H3～H4 | Chat、Knowledge、Alarm 通过 Registry 独立接入 |
| M4：可恢复生产链路 | H5～H6 | Alarm 恢复、统一追踪、预算与权限生效 |
| M5：扩展验收 | H7 | 新 Agent 无需修改 Runtime 即可上线 |

## 8. 暂不纳入本轮改造

- 不拆分微服务。
- 不开发可视化工作流编辑器。
- 不自研新的图执行引擎。
- 不立即把 Harness 发布成独立 SDK。
- 不为了统一形式而把 Alarm 强制改成自由 ReAct。
- 不在第一阶段引入 Kafka、Redis 或完整可观测平台。

完成 H7 后，再根据是否存在第二个项目复用该 Harness，决定是否将 `app/harness` 提取成独立包。
