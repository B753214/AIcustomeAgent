# 记忆系统基线指标快照（Memory-M0-4）

> 快照日期：**2026-09-25**  
> 用例来源：[tests/fixtures/memory_baseline.jsonl](../tests/fixtures/memory_baseline.jsonl)（M0-3）  
> 分类/策略：[memory_taxonomy.md](./memory_taxonomy.md)、[memory_data_policy.md](./memory_data_policy.md)  
> 目的：记录改造前状态，供 M1+ 各阶段对比。本步不上 Dashboard（M7）。

---

## 1. 环境

| 项 | 值 |
|----|-----|
| 项目 | AICustomeRobort |
| 快照日 | 2026-09-25 |
| APP_VERSION | 以 `.env` / Settings 为准（代码默认 `0.1.0`） |
| 会话截断 | `memory_max_turns = 5`（读最近 10 条消息） |
| 语义缓存 | `cache_enabled = true`（默认）；阈值 0.75 / 词面 0.5；容量 1000 |
| 用户隔离 | **无** `user_id`；`ChatRequest.session_id` 默认 `"default"` |
| 摘要 / Episodic | **无** |
| Run / Checkpoint | **有** `harness_runs` / `harness_run_events` / `harness_checkpoints` |
| 消息元数据 | 仅 `role` / `content` / `created_at` |
| 装配入口 | `services/chat` + Harness ChatExecutor → `run_astream` |

手测 P95 / 精确 Token / 线上命中率：本次 **未测** → 记为 `N/A`（有数据后可补一节）。

---

## 2. 基线用例汇总（M0-3）

| 指标 | 数量 |
|------|-----:|
| 用例总数 | 12 |
| `pass` | 4 |
| `partial` | 2 |
| `fail` | 6 |

| id | category | baseline_status | 一句话 |
|----|----------|-----------------|--------|
| chat-multi-001 | chat_multi_turn | pass | 闲聊多轮 |
| chat-order-001 | chat_tool | pass | 订单工具意图 |
| rag-basic-001 | rag | pass | 退货知识问答 |
| rag-followup-001 | rag_followup | **partial** | 「运费谁出」缺检索改写 |
| alarm-full-001 | alarm | pass | 完整告警模板 |
| alarm-followup-001 | alarm_followup | **fail** | 「看第 2 页」无 episode |
| isolation-history-001 | isolation | **fail** | 跨用户 history |
| isolation-default-001 | isolation_default | **fail** | 共享 default 会话 |
| cache-knowledge-001 | cache | partial | 有缓存、无严格 scope 验证 |
| cache-isolation-001 | cache_isolation | **fail** | 缓存无 user scope |
| long-context-001 | long_context | **fail** | 超 5 轮丢早期事实 |
| metadata-trace-001 | observability | **fail** | 消息无 intent/run_id |

**合格率（按 pass 计）：** 4/12 ≈ **33%**。  
**硬缺口（必须 fail→pass）：** 隔离 ×2、Alarm 追问、长上下文、消息追溯、缓存隔离。

---

## 3. 能力对照（改造前）

| 能力 | 基线结论 | 主要对应阶段 |
|------|----------|--------------|
| Short-term 多轮闲聊/基础 RAG/完整告警 | 基本可用 | 保持并完善 |
| 去 default / user 隔离 | 失败 | **M1** |
| 消息 ↔ harness Run | 失败 | **M2** |
| Token 预算 + Summary | 失败（长上下文） | **M3** |
| RAG 追问改写 | 部分 | **M6-RAG** |
| Alarm 会话 episode | 失败 | **M6-A** |
| Cache 用户隔离 | 失败 | **M7-1** |
| Semantic 长期事实 | 未覆盖（无能力） | **M4/M5** |

---

## 4. 可选指标（本次 N/A）

| 指标 | 基线值 | 备注 |
|------|--------|------|
| 语义缓存 hit_rate | N/A | 可从 `/api/v1/stats` 手抄补录 |
| Memory 装配 P95 | N/A | 尚无独立装配模块 |
| 跨用户泄露率 | 基线视为 **高风险（未隔离）** | 目标 0（M1） |
| 记忆额外 Token 占比 | N/A | M3 后测 |

---

## 5. 后续如何对比

1. 保持 `memory_baseline.jsonl` 的 `id` / 输入不变。  
2. 每完成 M1 / M3 / M6 / M7-1，更新各 id 的实际结果，目标：  
   - 隔离与 default相关 → `pass`  
   - alarm-followup / long-context / metadata-trace / cache-isolation → `pass`  
   - rag-followup → `pass`（或明确 partial 可接受）  
3. 本报告可追加「修订记录」小节，勿改写原基线数字（可另起「复测表」）。

---

## 6. 验收（M0-4）

- [x] 有日期与环境说明  
- [x] 引用 M0-3 计数与逐条状态  
- [x] 缺测项标明 N/A  
- [x] 不要求 Dashboard  
