# Knowledge RAG 评测报告

- 样本数：55
- Embedding：qwen3.7-text-embedding
- Reranker：qwen3.7-text-rerank（enabled=True）
- 召回 Top-K：20
- 重排：候选 20 条，输出 5 条

## 检索对比

| 模式 | K | Hit@K | MRR | P50(ms) | P95(ms) |
|---|---:|---:|---:|---:|---:|
| rerank | 5 | 100.00% | 0.9697 | 315.32 | 450.53 |

## 回答质量

- LLM Judge 平均分：4.75 / 5
- 正确来源命中率：100.00%

## 未命中样本

无。
