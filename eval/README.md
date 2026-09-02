# Agent 效果评测

`eval/` 用来评价 Agent 效果，`tests/` 用来验证代码行为。两者不要混用：单元测试回答“代码是否按设计执行”，评测回答“Agent 的路由、工具轨迹和最终结果是否足够好”。

## 目录

```text
eval/
├── agent_scoring.py          # 纯离线评分、聚合和报告生成
├── run_agent_eval.py         # Router / Chat / Alarm / Crew 统一入口
├── run_eval.py               # RAG 专项：检索、Judge、RAGAS
├── dataset/
│   ├── agent_cases.jsonl     # Agent 路由与轨迹样本
│   └── qa.jsonl              # RAG 问答样本
└── reports/                  # JSON 明细和 Markdown 汇总
```

## 快速使用

先运行不需要真实 LLM 或外部服务的告警规则评测：

```powershell
conda run -n agent-test python eval/run_agent_eval.py --agents alarm_rule
```

运行 Router 和 Chat；建议重复 3 次观察模型稳定性：

```powershell
conda run -n agent-test python eval/run_agent_eval.py --agents router chat --repeat 3
```

运行 RAG 专项评测：

```powershell
conda run -n agent-test python eval/run_eval.py --limit 5 --no-ragas
```

完整告警和 Crew 样本默认 `enabled=false`，因为它们可能访问 MCP、浏览器或产生更多模型费用。补充脱敏、可访问的真实样本后执行：

```powershell
conda run -n agent-test python eval/run_agent_eval.py --agents alarm crew --include-disabled
```

## 样本格式

每行是一个 JSON 对象：

```json
{
  "id": "chat-order-001",
  "agent": "chat",
  "category": "order",
  "input": "查订单 888888",
  "history": [],
  "expected": {
    "exact": {"intent": "order"},
    "tools": ["query_order"],
    "required_all": ["888888", "已发货"],
    "forbidden": ["查询失败"],
    "hard_checks": ["intent", "tools"]
  }
}
```

支持的自动检查：

| 字段 | 含义 |
|---|---|
| `exact` | 按字段路径精确比较，例如 `parsed.configId` |
| `tools` | 工具集合必须完全一致，忽略顺序和重复记录 |
| `required_all` | 最终回答必须包含全部短语 |
| `required_any` | 最终回答至少包含一个短语 |
| `forbidden` | 最终回答不得包含；命中后直接硬失败 |
| `sources_contains` | 至少有一个来源包含指定文本 |
| `tool_error` | 是否预期工具失败 |
| `max_tool_calls` | 最大工具调用记录数 |
| `min_judge_score` | 外部 Judge 分数下限，预留给后续 Judge 接入 |
| `hard_checks` | 指定检查失败时，无论总分多少都判失败 |

## 数据集建设建议

- Router：每个意图至少 30 条，重点加入相似边界样本；告警召回率单独统计。
- Chat：覆盖无工具、订单、天气、MCP、工具超时、空返回和连续失败。
- Alarm：优先使用脱敏真实事件，标注配置 ID、类型、证据、确认根因和禁止结论。
- RAG：训练/调 Prompt 集与最终验收集分离，补充知识库无答案样本。
- Crew：与非 Crew 路径使用完全相同的数据集，比较质量增益、P95 和费用。

自动评分适合检查路由、轨迹、字段和事实短语；Alarm 根因质量仍需人工抽检。建议在报告之外保存人工标签：`correctness`、`evidence`、`actionability`、`safety`，每项 1～5 分，并把“编造数据、泄露信息、无证据确定根因”设为硬失败。

## 报告解读

报告同时生成 JSON 和 Markdown。重点关注：

- `pass_rate`：满足样本验收条件的比例。
- `hard_failures`：安全或核心契约失败数，必须单独处理。
- `intent_accuracy`：包含意图期望的样本准确率。
- `tool_precision/recall/f1`：工具选择质量。
- `latency_p50_ms` / `latency_p95_ms`：运行时延分布。

不要只比较总分。版本上线前至少要求高风险硬失败不增加、Alarm Recall 不下降、工具幻觉不增加，再比较平均分、延迟和费用。
