# 记忆分类与存储边界（Memory-M0-1）

> 对应 [记忆系统跟做计划.md](./记忆系统跟做计划.md) / [记忆系统完善计划.md](./记忆系统完善计划.md)。  
> 目的：明确六类记忆各自存哪、活多久、禁止用途，避免混表。

---

## 1. 总览

| 类别 | 现状 | 动作 | 存储位置 | 生命周期 | 主要读者 |
|------|------|------|----------|----------|----------|
| Short-term | 已有 | **完善** | `chat_sessions` / `chat_messages` | 跟 session；读侧按 Token/轮数窗口 | 模型 Prompt、前端历史 |
| Summary | 无 | **新建** | `session_summaries`（待建） | 跟 session；覆盖已总结的旧消息 | ContextBuilder |
| Episodic | 无结构化 | **轻量新建** | `chat_sessions.last_alarm_episode`（JSONB，待加） | 跨轮、跟 session；被新任务覆盖 | Alarm 追问合并逻辑 |
| Execution | 已有 | **不动** | `harness_checkpoints` | 同一次 `run_id`；resume 后可过期清理 | Alarm Pipeline / Runtime |
| Semantic | 无 | **后期新建** | `memory_facts`（M4） | 跨会话；可 supersede / 删除 | 召回后注入 Prompt（M5） |
| Cache | 已有 | **治理** | 进程内 `SemanticCache`（可迁 Redis） | 可丢；TTL/容量淘汰 | chat 入口加速 |

**Run 台账（辅助，不算用户记忆层）：** 已有 `harness_runs` / `harness_run_events`；消息通过 `run_id` 关联，**禁止**再建平行 `agent_runs`。

---

## 2. 分类细则

### 2.1 Short-term（短时 / 会话对话）

| 项 | 说明 |
|----|------|
| **存什么** | 用户说了什么、助手回了什么（对话原文） |
| **现在有什么** | `role`、`content`、`created_at`；全量写入，读取最近 `memory_max_turns * 2` 条 |
| **完善方向** | 去共享 `default`；加 `user_id` 隔离；Token Budget；消息挂 intent/engine/`run_id`/metadata |
| **禁止** | 把 pipeline 中间态、tool_fail_counts、幂等键当聊天消息堆进表且无预算 |
| **谁读写** | `session_service` 写；`services/chat` / ContextBuilder 读进 Prompt；历史 API 读 |

### 2.2 Summary（摘要）

| 项 | 说明 |
|----|------|
| **存什么** | 更早轮次的结构化压缩：topic / known_facts / decisions / unresolved |
| **现状** | 无；超窗口的旧消息对模型「直接消失」 |
| **新建** | `session_summaries` + 滚动生成；记录 `through_message_id`、`prompt_version` |
| **禁止** | 用摘要替代库内原文真相；摘要失败时阻断主对话 |
| **谁读写** | Summary Service 写；ContextBuilder 读（摘要块 + 未覆盖的最近原文） |

### 2.3 Episodic（会话级任务名片）

| 项 | 说明 |
|----|------|
| **存什么** | 某次任务可程序复用的结论名片，例如 Alarm：`config_id`、monitor URL、页码、证据摘要、playbook 提示、可选 `source_run_id` |
| **现状** | 无；仅可能混在 assistant `content` 散文里，代码无法稳定读取；Alarm 追问不读历史 |
| **落地口径** | **不是**独立记忆中台；优先 `chat_sessions.last_alarm_episode` JSONB |
| **禁止** | 写入 `harness_checkpoints`；与 Short-term 原文重复建第二套聊天库 |
| **谁读写** | Alarm 跑完写；下一轮追问合并读 |

**过关口令：**

- 「Alarm 看第 2 页」→ 读 **`last_alarm_episode`**（Episodic）  
- 「同一次 Run 中断后续跑」→ 读 **`harness_checkpoints`**（Execution）

### 2.4 Execution（执行状态 / Checkpoint）

| 项 | 说明 |
|----|------|
| **存什么** | 当前 Run 做到哪一步、可恢复 payload、幂等键相关状态 |
| **现状** | 已有 `harness_checkpoints`（Harness H5）；Alarm 同 Run resume 可用 |
| **动作** | **不改 schema 来存聊天或跨轮追问**；本专题只守边界 |
| **禁止** | 存用户偏好、完整聊天历史、跨轮「看第 2 页」情景 |
| **谁读写** | `harness_storage.persist` / Alarm executor |

### 2.5 Semantic（长期事实）

| 项 | 说明 |
|----|------|
| **存什么** | 跨会话稳定事实：偏好、身份约束、业务稳定事实等 |
| **现状** | 无 |
| **新建（M4/M5）** | `memory_facts`；候选/确认/冲突 supersede；再向量召回 |
| **禁止** | 临时天气、单次订单状态、无审核的模型猜测直接变 `active` |
| **谁读写** | Memory Policy 写；Retriever 读后注入 Prompt（受 Token 上限） |

### 2.6 Cache（语义缓存）

| 项 | 说明 |
|----|------|
| **存什么** | 问句向量 + 原问句 + 可复用的 `result`（reply/intent/sources…） |
| **现状** | `app/services/semantic_cache.py`；chat 首轮非告警可命中 |
| **治理方向** | key 含 user/session scope；TTL/版本；个性化/订单/告警默认不进共享 |
| **禁止** | 当作用户记忆真相源；跨用户共享命中 |
| **谁读写** | `services/chat` 入口 |

---

## 3. 禁止混用对照

| 场景 | 正确落点 | 错误落点 |
|------|----------|----------|
| 多轮闲聊上下文 | Short-term（± Summary） | Checkpoint / Cache |
| 告警「看第 2 页」 | Episodic（session JSON） | `harness_checkpoints` |
| Run 中断续跑 | Execution（`harness_checkpoints`） | `chat_messages` / episode |
| 「用户喜欢简洁回答」 | Semantic（后期） | 仅写进某次 reply 当永久事实 |
| 相同知识问答加速 | Cache | 当成跨会话记忆 |

---

## 4. 与代码现状对照

| 组件 | 路径 | 备注 |
|------|------|------|
| 会话消息 | `app/models/sessions.py` | Short-term 真相源雏形 |
| 会话读写 | `app/services/session_service.py` | 按轮数截断读 |
| 语义缓存 | `app/services/semantic_cache.py` | Cache 已有 |
| Run / Event / Checkpoint | `app/harness_storage/models.py` | Execution + Run 台账已有 |
| 脱敏 | `app/harness/policies/data.py` | 会话写入应对齐（M2-4） |
| 装配入口 | `app/services/chat.py`（及 Adapter 传入 session） | **不改** AgentRuntime 核心塞记忆 |

---

## 5. 验收（M0-1）

- [x] 六类均有：现状、存储、生命周期、禁止用途  
- [x] Episodic 与 Execution 场景口令答案不同  
- [x] 明确 Short-term/Cache/Execution 已有；Summary/Semantic 新建；Episodic 为 session 字段  

本步不改业务代码、不建表。
