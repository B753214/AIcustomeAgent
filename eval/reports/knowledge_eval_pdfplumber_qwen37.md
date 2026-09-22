# Knowledge RAG 评测报告

- 样本数：55
- Embedding：qwen3.7-text-embedding
- Reranker：qwen3.7-text-rerank（enabled=True）
- 召回 Top-K：20
- 重排：候选 20 条，输出 5 条

## 检索对比

| 模式 | K | Hit@K | MRR | P50(ms) | P95(ms) |
|---|---:|---:|---:|---:|---:|
| vector | 20 | 100.00% | 0.9258 | 143.13 | 283.15 |
| bm25 | 20 | 100.00% | 0.9067 | 4.74 | 7.5 |
| hybrid | 20 | 100.00% | 0.9212 | 145.04 | 225.67 |
| rerank | 5 | 100.00% | 0.9697 | 318.88 | 446.86 |

## 未命中样本

无。
