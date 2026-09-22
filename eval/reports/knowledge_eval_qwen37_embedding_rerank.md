# Knowledge RAG 评测报告

- 样本数：55
- Embedding：qwen3.7-text-embedding
- Reranker：qwen3.7-text-rerank（enabled=True）
- 召回 Top-K：20
- 重排：候选 20 条，输出 5 条

## 检索对比

| 模式 | K | Hit@K | MRR | P50(ms) | P95(ms) |
|---|---:|---:|---:|---:|---:|
| vector | 20 | 98.18% | 0.9000 | 137.64 | 231.11 |
| bm25 | 20 | 98.18% | 0.8938 | 3.78 | 5.57 |
| hybrid | 20 | 100.00% | 0.8834 | 146.12 | 242.19 |
| rerank | 5 | 100.00% | 0.9788 | 332.24 | 452.01 |

## 未命中样本

- `vector` / `doc-046-1`：在动态UI架构中，AJX引擎层提供的调试能力具体包括哪些功能？（期望 深入理解动态UI架构.pdf）
- `bm25` / `doc-036-1`：AJX前端在iOS和Android平台上分别使用什么JavaScript引擎来执行业务逻辑？（期望 前端基本介绍.pdf）
