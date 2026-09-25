# Harness ↔ Eval 对照与基线（H7-2）

指标与脚本沿用现有 `eval/`，**不另起评分体系**。  
单元测试（`tests/`）验代码行为；本目录验 Agent / RAG **效果**。使用细则见 [eval/README.md](../eval/README.md)。

## 对照表

| Harness / 能力 | Eval 脚本 | `--agents` / 模式 | 样本 | 主要指标（沿用现有） | 费用 / 依赖 |
|---|---|---|---|---|---|
| Router（`classify` → `agent_id`） | `eval/run_agent_eval.py` | `router` | `eval/dataset/agent_cases.jsonl` | `intent_accuracy`、`pass_rate`、`hard_failures` | 需 LLM |
| Chat（`agent_id=chat`） | 同上 | `chat` | 同上 | `pass_rate`、`tool_precision/recall/f1`、`latency_p95_ms` | 需 LLM；工具可能外连 |
| Alarm 规则层（parse / classify / detect） | 同上 | `alarm_rule` | 同上 | `pass_rate`、`intent_accuracy`、字段 `exact` | **零费用、离线** |
| Alarm 全链路（`agent_id=alarm`） | 同上 | `alarm` | 同上（默认 `enabled=false`） | 结论短语、`sources_contains`、硬失败 | 需 LLM / MCP / 浏览器；加 `--include-disabled` |
| Knowledge / RAG（`agent_id=knowledge`） | `eval/run_eval.py` | `--limit` / `--no-ragas` 等 | `eval/dataset/qa.jsonl` | Judge 分、关键词命中；可选 RAGAS | 需 LLM + Embedding + PG/Milvus |
| Knowledge 检索策略对比 | `eval/run_knowledge_eval.py` | 见脚本 `--help` | `eval/dataset/knowledge_qa.jsonl` | 检索命中 / MRR 等 | 需向量库与模型 |
| Crew（非 Harness 主路径） | `run_agent_eval.py` | `crew` | `agent_cases.jsonl`（默认 disable） | 与 Chat 同集对比质量 / 延迟 | 费用更高 |

> Harness Runtime 只统一 Run/事件/策略；评测仍直接打领域入口（与 H7-2「挂现有 eval」一致）。以后若加 Harness 包装跑法，复用同一套 `expected` 与报告字段即可。

## 推荐命令

```powershell
# 零费用基线（CI / 本地必跑）
conda run -n agent-test python eval/run_agent_eval.py --agents alarm_rule

# 有 LLM 时：路由 + 闲聊（可加 --repeat 3）
conda run -n agent-test python eval/run_agent_eval.py --agents router chat --repeat 3

# RAG 冒烟（需 .env 与库）
conda run -n agent-test python eval/run_eval.py --limit 5 --no-ragas

# 完整 Alarm / Crew（需脱敏可访问样本）
conda run -n agent-test python eval/run_agent_eval.py --agents alarm crew --include-disabled
```

报告默认写到 `eval/reports/agent_report_YYYYMMDD_HHMMSS.{json,md}`（可用 `--out` 指定）。

## 基线记录（H7-2 验收）

| 项 | 值 |
|---|---|
| 日期 | 2026-09-25 |
| 环境 | `conda` env `agent-test`，Python **3.12.13** |
| 命令 | `python eval/run_agent_eval.py --agents alarm_rule` |
| 数据集 | `eval/dataset/agent_cases.jsonl`（5 条 `alarm_rule`） |
| 报告 | [agent_report_20260925_155014.md](../eval/reports/agent_report_20260925_155014.md) / `.json` |

**结果摘要**

| Agent | 样本 | 通过率 | 平均分 | 硬失败 | Intent Acc | P95(ms) |
|---|---:|---:|---:|---:|---:|---:|
| alarm_rule | 5 | 100% | 100.0 | 0 | 1.0 | 6.06 |

复现：在仓库根目录用上表命令即可；通过率应保持 100%、硬失败为 0（规则层无外部依赖）。

## 与 H7-1 / H7-3

- **H7-1**：离线 `tests/` 分层（Contract / Unit / Golden / Replay / Failure），见 [harness_test_layers.md](./harness_test_layers.md)。  
- **H7-3**：新增玩具 Agent 只注册；效果评测仍可按上表扩展 `agent_cases.jsonl` 一行，不必改 Runtime。
