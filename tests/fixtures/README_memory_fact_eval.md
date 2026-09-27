# memory_fact_eval.jsonl

Memory-M7-4：长期事实写入 / 召回评测集（离线，不调真 LLM）。

- 路径：`tests/fixtures/memory_fact_eval.jsonl`
- 跑手：`pytest tests/test_memory_fact_eval.py -q`
- `category`：`write_ok` | `write_reject` | `conflict` | `forget` | `recall_inject` | `isolation`
- `skip: true` 的行由其它单测覆盖，跑手会跳过
