# 记忆数据保留策略（Memory-M0-5 Retention Policy）

> 对应跟做计划 M0-5。  
> **规则在本文；清理命令与定时见 §6（M1-5 已实现）。**  
> 删除/脱敏原则对齐 [memory_data_policy.md](./memory_data_policy.md)。

---

## 1. 原则

1. **用户可删：** 用户发起的会话清空/删除优先于默认保留期。  
2. **越敏感越短：** Checkpoint、含工具细节的 events 默认短于纯对话原文（若合规要求更严则从其规定）。  
3. **Cache 可丢：** 语义缓存不是真相源，TTL 内自然淘汰即可。  
4. **Run 与消息可解耦保留：** 删会话消息时，是否级联删 `harness_runs` 见下表（默认：会话删则建议匿名化或延迟删 Run，便于审计）。  
5. **时区：** 保留期按 **UTC 日历日** 计算（落库后统一 `TIMESTAMPTZ` / UTC）。

以下天数为**建议默认值**，上线前可按合规调整；改数字不改对象分类。

---

## 2. 保留期限表

| 对象 | 存储 | 默认保留 | 到期动作 | 谁触发 |
|------|------|----------|----------|--------|
| 活跃会话消息 | `chat_messages` | 随 session；session **最后活动**后 **180 天** | 归档或删除 | M1-5 任务 / 用户删除 |
| 已 ended/archived 会话 | `chat_sessions` + messages | ended 后再留 **30 天** | 删除（级联消息） | M1-5 |
| 用户主动清空历史 | messages | 立即 | `DELETE` 消息，保留 session 壳 | API |
| 用户删除会话 | session | 立即 | 软删 `status=deleted` 或硬删；**7 天内**可硬清理 | API + M1-5 |
| `last_alarm_episode` | session JSON | **跟 session** | session 删则一起没 | 级联 |
| `session_summaries` | 待建 | **跟 session** | 同会话消息 | 级联 |
| `harness_runs` | PG | **90 天**（自 `ended_at`） | 删除或归档冷存储 | M1-5 / 运维 |
| `harness_run_events` | PG | **与所属 Run 相同**或 Run 结束后 **90 天** | 随 Run 删 | 级联优先 |
| `harness_checkpoints` | PG | Run **终态后 7 天**；或 Run 删除时级联 | 删除 | M1-5 |
| `memory_facts`（M4） | PG | 用户删除立即失效；其余 **无限**直至用户/运营清理 | `status=deleted` 后 **30 天**硬删 | API + 任务 |
| 记忆审计日志（M4-7） | 待建 | **365 天** | 归档 | 运维 |
| Semantic Cache | 进程内存 | **TTL 建议 24h**；容量 LRU/`max_entries_cache` | 自然淘汰 | 缓存自身（M7-2） |
| 浏览器 profile | `.browser_profile/` | 本地；**不进 Git** | 手工/磁盘策略 | 运维；勿入记忆库 |

---

## 3. 状态与生命周期（会话）

```text
active  --结束/超时-->  ended / archived
                \-->  deleted（用户或保留任务）
```

| status | 含义 | 是否允许继续写入 |
|--------|------|------------------|
| `active` | 正常 | 是 |
| `ended` | 用户或系统结束 | 否（或仅只读追问策略，默认否） |
| `archived` | 保留期内只读 | 否 |
| `deleted` | 待清理/已不可见 | 否 |

`expires_at`（若 M1 增加）：超过则视为可归档候选。

---

## 4. 删除与审计

| 动作 | 要求 |
|------|------|
| 用户清空/删除 | 写审计（谁、何时、哪个 session）；内容本身按策略抹除 |
| 定时清理 | 干跑日志（将删数量）→ 执行 → 汇总 |
| 跨用户 | 清理任务必须按 `user_id` 过滤，禁止全表误扫他户（M1 后） |
| 敏感误存 | 一经发现按 data_policy **立即删/打码**，不等待保留期 |

---

## 5. 与 Checkpoint / Episode 的关系

| 数据 | 保留语义 |
|------|----------|
| Checkpoint | **短**；只服务同 Run 恢复，终态后尽快可删 |
| Episode | **跟会话**；不是 Run 级，不要按 7 天 Checkpoint 策略误删仍在聊的 session 名片 |

---

## 6. 清理方法（M1-5 已实现）

**不会自动清。** API 只做软删 / 改 status；过期硬删必须跑脚本（或自行挂系统定时任务）。不上 Celery。

### 6.1 命令

在项目根目录 `AICustomeRobort/`、已配置好 `POSTGRES_URI` 的同一环境中执行：

```bash
# 干跑：只统计将删数量，不写库
python -m app.jobs.memory_retention --dry-run

# 正式清理（每批最多 N 条 runs / sessions；默认 200）
python -m app.jobs.memory_retention --limit 200
```

输出为 JSON，含 `checkpoints` / `runs` / `sessions` 的 `would_delete` 或 `deleted` 与 `cutoff`。

### 6.2 清理顺序与规则

| 步骤 | 对象 | 条件（默认天数见 §2 / `app/jobs/config.py`） | 行为 |
|------|------|-----------------------------------------------|------|
| 1 | `harness_checkpoints` | 所属 Run 终态且 `ended_at` 超 **7** 天 | 硬删 |
| 2 | `harness_runs`（及 events/checkpoints） | 终态且 `ended_at` 超 **90** 天 | 先删 event/checkpoint，再删 run |
| 3a | `chat_sessions` | `ended`/`archived` 且 `ended_at` 超 **30** 天 | 硬删（消息 FK CASCADE） |
| 3b | `chat_sessions` | `deleted` 且 `updated_at` 超 **7** 天 | 硬删（同上） |

暂未做：`active` 闲置 180 天自动归档（常量 `retention_active_idle_days` 仅预留）。

### 6.3 建议定时（可选）

先 `--dry-run` 看 counts，再正式跑。例如每天一次：

```text
# Linux / macOS cron（按本机 python 路径改）
0 3 * * * cd /path/to/AICustomeRobort && python -m app.jobs.memory_retention --limit 500 >> /var/log/memory_retention.log 2>&1
```

Windows：任务计划程序 → 每天触发 → 操作设为同上 `python -m app.jobs.memory_retention`。

### 6.4 代码落点

| 文件 | 作用 |
|------|------|
| `app/jobs/memory_retention.py` | CLI + `run_retention` |
| `app/jobs/config.py` | 保留天数常量 |
| `app/harness_storage/*_repository.py` | run / checkpoint / event 批量删与 count |
| `tests/test_memory_retention.py` | 规则单测 |

---

## 7. 验收（M0-5）

- [x] 会话、Run、Event、Checkpoint、Episode、Cache、（预告）facts 均有保留表述  
- [x] 区分用户删除 vs 到期清理  
- [x] 标明实现落点 M1-5，本步无强制代码  

---

## 8. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-09-25 | 初版建议天数；上线前可按合规修改数字 |
| 2026-09-26 | §6 改为 M1-5 实操说明（命令 / 顺序 / 定时） |
