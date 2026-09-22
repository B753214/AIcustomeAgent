# AICustomeRobort 实施计划

对标智能客服能力：**会话 → PostgreSQL，向量 → Milvus**。

---

## 当前主线

下一步改造看这一份：

- **[Harness改造计划.md](./Harness改造计划.md)** — 模块化 Harness + 可插拔 Chat / Knowledge / Alarm

对话里可以说：`开始 Harness-DayN`（以该文档内章节为准）。

---

## 常查阅

| 文件 | 用途 |
|------|------|
| [架构与数据模型.md](./架构与数据模型.md) | 技术栈、目录、表结构、接口字段 |
| [Harness改造计划.md](./Harness改造计划.md) | 当前改造目标与阶段 |

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
