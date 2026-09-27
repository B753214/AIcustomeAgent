# 会话 Episode ≠ Harness Checkpoint（Memory-M6-0）

> 对应跟做计划 **M6-0**。  
> 分类总表见 [memory_taxonomy.md](./memory_taxonomy.md)；字段允许/禁止见 [memory_data_policy.md](./memory_data_policy.md)。  
> **本页只定边界，不改表、不写业务代码。** 读写实现见后续 **M6-A**。

---

## 1. 一句话

| 概念 | 一句话 |
|------|--------|
| **Episode**（`last_alarm_episode`） | 跟 **会话** 的任务名片，给「下一轮人话追问」用 |
| **Checkpoint**（`harness_checkpoints`） | 跟 **同一次 Run** 的步骤快照，给「中断后续跑」用 |

二者 **禁止混用、禁止互写**。

---

## 2. 对照表

| 维度 | Episodic：`chat_sessions.last_alarm_episode` | Execution：`harness_checkpoints` |
|------|-----------------------------------------------|----------------------------------|
| 主键/归属 | `session_id`（+ `user_id` 属主） | `run_id` + step / 幂等键 |
| 生命周期 | 跨多轮对话；新完整告警可 **覆盖**；随 session 删 | 单次 Run 内；Run 终态后按保留期清理 |
| 典型问题 | 「看第 2 页」「继续查这个 config」 | 浏览器步骤做到一半进程挂了，同 Run resume |
| 内容形态 | 稳定字段名片：config / url / 页码 / 证据摘要… | 步骤名 + 可恢复 payload（H5 约定） |
| 谁读写 | Alarm 成功路径写；下一轮追问合并读（M6-A） | `harness_storage` / Alarm Executor |
| 与聊天关系 | 可从本轮结果提炼；**不是**第二套消息表 | **不存**完整聊天、不存跨轮追问语义 |

---

## 3. 过关口令（评审用）

| 场景 | 读哪里 | 不读哪里 |
|------|--------|----------|
| 用户说「看第 2 页」 | **`last_alarm_episode`** | `harness_checkpoints` |
| 同一次 Alarm Run 中断后续跑 | **`harness_checkpoints`** | `last_alarm_episode` |
| 用户偏好「回复简洁」 | `memory_facts`（Semantic） | episode / checkpoint |
| 上周同会话聊过什么 | `chat_messages` / Summary | checkpoint |

答错即边界没守住。

---

## 4. 硬禁止

1. **禁止**把跨轮追问名片写入 `harness_checkpoints`，或为此改 H5 checkpoint schema / 幂等约定。  
2. **禁止**用 checkpoint resume 逻辑冒充「看第 2 页」会话追问。  
3. **禁止**把完整抓取原文、Cookie、密码放进 episode（对齐 data policy）。  
4. **禁止**为 Episodic 另建「记忆中台」大表；第一版就是 session 上 JSON 列（M6-A）。  
5. **禁止**一会话堆多份并行 episode 而不覆盖——第一版 **一张当前名片**，新完整告警覆盖旧的。

---

## 5. 与 M6-A 的交界

| M6-0（本文） | M6-A |
|--------------|------|
| 定义边界与口令 | 加列 / Schema / `get`·`save`·`merge` / 挂 chat |
| 不写代码 | 实现「跑完写、追问读」 |

M6-A 验收仍用本文口令：「看第 2 页」只依赖 episode，不碰 checkpoint 表。

---

## 6. 验收（M6-0）

- [x] 有独立说明页（本文）  
- [x] Episode / Checkpoint 对照表 + 过关口令  
- [x] 硬禁止写清（含不改 H5 checkpoint）  
- [x] 跟做计划勾选 M6-0  
