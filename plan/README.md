# AICustomeRobort 实施计划

对标智能客服能力：**会话 → PostgreSQL，向量 → Milvus**。

---

## 当前主线

可并行跟做：

- **[记忆系统跟做计划.md](./记忆系统跟做计划.md)** — **按完善计划 M0～M7 逐步跟做（记忆主跟做）**
- **[记忆系统完善计划.md](./记忆系统完善计划.md)** — 记忆完整版蓝图
- **[记忆系统优化.md](./记忆系统优化.md)** — 精简第一版（Mem-Day；备选）
- **[Harness改造计划.md](./Harness改造计划.md)** — Harness 完整蓝图（保留）
- **[Harness跟做计划.md](./Harness跟做计划.md)** — 按旧蓝图 H0～H7 逐步跟做
- **[AgentRuntime改造计划.md](./AgentRuntime改造计划.md)** — 精简执行版（备选）

对话里可以说：`开始 Memory-M0-1`、`完成 Memory-M0-1`、`开始 Harness-H0-1`。

---

## 常查阅

| 文件 | 用途 |
|------|------|
| [记忆系统跟做计划.md](./记忆系统跟做计划.md) | 记忆 M0～M7 施工跟做 |
| [记忆系统完善计划.md](./记忆系统完善计划.md) | 记忆完整版蓝图与指标 |
| [记忆系统优化.md](./记忆系统优化.md) | 记忆精简第一版（Mem-Day） |
| [架构与数据模型.md](./架构与数据模型.md) | 技术栈、目录、表结构、接口字段 |
| [Harness改造计划.md](./Harness改造计划.md) | Harness 完整蓝图 |
| [Harness跟做计划.md](./Harness跟做计划.md) | H0～H7 逐步跟做（完整版） |
| [AgentRuntime改造计划.md](./AgentRuntime改造计划.md) | Runtime 精简执行版（备选） |

---

## 历史归档（已完成 / 不再跟做）

早期「从 0 跟做」、闲聊 Chat-SG、告警合并与 Replan 等文档已合并到：

| 归档 | 内容 |
|------|------|
| [archive/奠基与学习.md](./archive/奠基与学习.md) | 分步实施 + 进度 + 计划总表 + 任务清单 + 学习路线 |
| [archive/闲聊专题.md](./archive/闲聊专题.md) | StateGraph（完成）+ LangGraph（废弃）+ ReAct（历史） |
| [archive/告警专题.md](./archive/告警专题.md) | Agent 合并 + Plan-Execute-Replan + 改动计划表 |

细节以代码与主 README 为准；归档仅供回溯设计决策。

---

## 目标一句话

用户提问 → 判断知识/订单/闲聊/告警 → 知识类 RAG 再生成 → 可 SSE 流式 → 对话进 PostgreSQL，向量进 Milvus。CrewAI 可选；告警为约束型 Pipeline + Replan。
