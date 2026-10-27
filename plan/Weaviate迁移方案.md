# Milvus + 内存 BM25 → Weaviate 迁移方案

> 目标：用 **Weaviate** 统一承载 **向量检索 + BM25/Hybrid**，PostgreSQL 仍作业务与正文真相源。  
> 适用仓库：`AICustomeRobort`（当前 Milvus Standalone + `rank_bm25` 进程内索引）。

---

## 1. 迁移边界

### 1.1 替换什么

| 现状 | 迁移后 |
|---|---|
| Milvus Collection（ANN） | Weaviate Collection / Class |
| 进程内 `BM25Index`（jieba + rank_bm25） | Weaviate 内置 BM25 / Hybrid Search |
| `app/rag/fusion.py` RRF（自研双路融合） | 优先用 Weaviate `hybrid`；必要时保留自研融合作对比 |
| `docker-compose` 中 `milvus-standalone` | `weaviate` 服务 |

### 1.2 不替换什么

| 组件 | 原因 |
|---|---|
| **PostgreSQL**（sessions / messages / documents / chunks） | 会话、审计、chunk 正文真相源；Weaviate 只存检索副本 |
| Embedding 模型（`text-embedding-v3`） | 维数仍 1024；换库不换模型则向量可重导 |
| 文档解析 / 分块（`loader` / `split_text`） | 入库前逻辑不变 |
| RAG Prompt / 评测集（`eval/`） | 用同一套指标验收迁移 |
| Reranker（可选） | 仍可接在 hybrid 结果之后 |

### 1.3 非目标（本期不做）

- 用 Weaviate 替代 PG 存会话  
- 一次改完切分策略、换 embedding 模型（避免变量过多）  
- 上 Weaviate Cloud（可二期；本期先 self-host 对齐现有 compose）

---

## 2. 目标架构

```
上传/ingest
  → parse + split（不变）
  → 写 PG documents/chunks（真相源，建议补 replace）
  → embed（DashScope text-embedding-v3）
  → upsert Weaviate（vector + 文本属性，供 BM25）
  → （可选）删旧对象，保证同名文档不脏读

检索
  → Weaviate hybrid（vector + BM25）→ chunk_id 列表
  → 回表 PG 取 content（或直接用 Weaviate 返回的 content，需约定以谁为准）
  → 可选 rerank → RAG_PROMPT 生成
```

**推荐约定**：Weaviate 存 `content` 副本用于检索；**展示与生成仍以 PG 为准**（与现「Milvus 只存向量、回表取正文」一致，降低双写漂移风险）。若追求少一次往返，可直接用 Weaviate `content`，但更新路径必须强一致。

---

## 3. Weaviate Schema 设计

### 3.1 Collection 建议名

`CustomerChunk`（或配置项 `WEAVIATE_CLASS_NAME`）

### 3.2 属性

| 属性 | 类型 | 说明 |
|---|---|---|
| `chunk_id` | text / uuid（作 id） | = PG `chunk.id`，幂等 upsert 主键 |
| `document_id` | text | = PG `document.id` |
| `file_name` | text | 原始文件名，过滤/展示 |
| `chunk_index` | int | 拼 `file.md#3` |
| `content` | text | **tokenization=word**（中文需确认 tokenizer；必要时预分词或用 `gse`/`jieba` 预处理字段） |
| `content_vector` | vector `[1024]` | 与 `DIM=1024`、embedding 模型对齐 |
| `content_sha256` | text（可选） | 便于跳过未变更 |

### 3.3 检索配置

- 向量距离：**cosine**（与现 Milvus `COSINE` 一致）  
- Hybrid：`alpha` 可配置（如 `0.5` 起，用 eval 调）  
- 中文 BM25：Weaviate 默认分词对中文可能偏弱 → **POC 必测**；不行则：
  - 增加 `content_jieba` 字段（空格分隔的预分词文本）专供 BM25，或  
  - Hybrid 仅向量 + 保留轻量自研 BM25（过渡期）

### 3.4 索引 / 模块

- Self-host：启用 text2vec **外部向量**（Bring Your Own Vectors），**不要**默认改用 Weaviate 内置另一套 embedding，避免与 DashScope 空间不一致。  
- 向量由应用侧 `embed_query` 写入（对齐现 `build_embedding()`）。

---

## 4. 代码改造映射

| 现文件 | 改造动作 |
|---|---|
| `app/rag/milvus_store.py` | 新增 `app/rag/weaviate_store.py`（create schema / upsert / search / delete_by_doc） |
| `app/rag/document_embedding.py` | upsert 目标改为 Weaviate；保留 PG 写入顺序：先 PG 成功再写向量库 |
| `app/rag/lexical.py` + `KnowledgeBase.build_index` | 默认关闭内存 BM25；hybrid 走 Weaviate；保留 `--legacy-bm25` 开关一版便于对比 |
| `app/rag/retriever.py` `search_*` | `search_vector` / `search_bm25` / `search_hybrid` 收敛为 `search_weaviate_hybrid`；或 vector/keyword 两路仍调 Weaviate 不同 API |
| `app/rag/fusion.py` | Hybrid 原生可用后降为可选；A/B 时保留 |
| `app/config.py` / `.env` | 增加 `WEAVIATE_URL`、`WEAVIATE_API_KEY`、`WEAVIATE_CLASS`、`HYBRID_ALPHA`、`VECTOR_BACKEND=milvus|weaviate` |
| `app/main.py` lifespan | `ensure_collection` → Weaviate schema ensure；health 检查 Weaviate |
| `docker-compose.yml` | 加 weaviate；Milvus 可先并存再下线 |
| `eval/run_eval.py` | 同一 `qa.jsonl` 对比 milvus-hybrid vs weaviate-hybrid |

**抽象建议**：先抽 `VectorStore` 协议（`upsert` / `search` / `delete_by_document`），Milvus / Weaviate 双实现，用 `VECTOR_BACKEND` 切换，降低一次性切死风险。

---

## 5. 分阶段实施

### Phase 0 — 准备（0.5～1 天）

- [ ] 冻结 embedding 模型与 `DIM=1024`（迁移期不换模型）  
- [ ] 补齐文档 **replace** 语义（按 `file_name` 删旧 chunk + 旧向量），否则迁完仍脏数据  
- [ ] 跑通基线：`python eval/run_eval.py --ingest data/knowledge_base.md`，保存 `eval/reports/*` 作为对照  
- [ ] 选定 Weaviate 版本（建议与官方 compose 对齐的稳定版）与 Python client（`weaviate-client` v4）

### Phase 1 — POC 双写（2～3 天）

- [ ] compose 增加 Weaviate（可与 Milvus 并存）  
- [ ] 实现 `weaviate_store`：建类、upsert、hybrid search、按 `document_id` 删除  
- [ ] ingest：**双写** Milvus + Weaviate（失败策略：PG 成功则记录补偿任务，避免只写一边）  
- [ ] 增加内部接口或脚本：`/retrieval` 可指定 `backend=milvus|weaviate`  
- [ ] 中文 BM25 效果冒烟（专有名词、短问「运费谁出」等）

**退出标准**：同一批问题，Weaviate hybrid 的关键词命中率 / ContextRecall 不低于现网基线的可接受阈值（例如 Recall 降幅 &lt; 5% 或持平）。

### Phase 2 — 读切换（1～2 天）

- [ ] `VECTOR_BACKEND=weaviate` 作为默认检索  
- [ ] 关闭启动时内存 BM25 `rebuild`（或仅 fallback）  
- [ ] health / stats 展示 weaviate 状态、对象数  
- [ ] 全量 `run_eval` + 人工抽查「知识库无覆盖应答不知道」类题

**退出标准**：评测与线上冒烟通过；P95 检索延迟可接受。

### Phase 3 — 全量迁移与下线 Milvus（1 天）

- [ ] 脚本：从 PG `chunks` 全量 embed（或复用已有向量若曾导出）→ Weaviate  
- [ ] 校验：PG `chunk_count` == Weaviate object count（按 collection）  
- [ ] 停止双写 Milvus；compose 移除 milvus；文档与 README 更新  
- [ ] 保留至少 1 个版本的回滚开关（见 §7）

### Phase 4 — 加固（可选，持续）

- [ ] ingest 异步化、失败重试与死信  
- [ ] 多租户 / 按 `file_name` 过滤检索  
- [ ] 监控：upsert QPS、hybrid 延迟、错误率  
- [ ] 若中文 BM25 不足：上 `content_jieba` 或外部分析器方案定稿

---

## 6. 数据迁移步骤（全量）

```text
1. 确保 PG chunks 完整（以 PG 为准）
2. ensure Weaviate schema（dim=1024, cosine）
3. 分页读取 Chunk(id, document_id, title, chunk_index, content)
4. 对每条：
     vector = embed(content)   # 与线上同一 embedding
     weaviate.upsert(chunk_id=id, ..., vector=vector, content=content)
5. 抽样检索对比 + count 校验
6. 切换读流量
```

注意：

- **不要**尝试从 Milvus「导出向量再导入」除非你能稳定导出且与 id 对齐；从 PG 正文重 embed 更简单可靠。  
- 大批量时控制并发与 DashScope 限流；可断点续跑（按 `chunk_id` 幂等 upsert）。

---

## 7. 回滚方案

| 触发 | 动作 |
|---|---|
| 评测明显变差 / 故障 | `VECTOR_BACKEND=milvus`，恢复内存 BM25 启动 rebuild |
| Weaviate 不可用 | health 降级：纯向量（若 Milvus 仍在）或返回「检索暂不可用」 |
| 双写期 | 读可切回 Milvus；写继续双写直到问题关闭 |

回滚前提：Phase 3 完成前 **不要删除** Milvus 数据卷。

---

## 8. 配置草案

```ini
# 后端切换
VECTOR_BACKEND=weaviate          # milvus | weaviate

# Weaviate
WEAVIATE_URL=http://localhost:8080
WEAVIATE_GRPC_URL=localhost:50051
WEAVIATE_API_KEY=
WEAVIATE_CLASS_NAME=CustomerChunk
WEAVIATE_HYBRID_ALPHA=0.5

# 保留（回滚期）
MILVUS_URI=http://localhost:19530
COLLECTION_NAME=customer_milvus_collection
DIM=1024
```

---

## 9. 验收清单

- [ ] `/health`：postgres=ok，weaviate=ok  
- [ ] ingest MD/PDF → PG 有行，Weaviate 有对象  
- [ ] 同名再传：旧对象删除或替换，检索无旧内容（依赖 replace）  
- [ ] hybrid 能命中关键词型问题与语义型问题  
- [ ] `eval/run_eval.py` 对比报告归档，核心指标不劣于基线约定  
- [ ] 重启 API：**无需**全量建内存 BM25 即可检索  
- [ ] 文档：README / 架构文档标明向量后端为 Weaviate  

---

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| 中文分词导致 BM25 变差 | POC 必测；预分词字段或短期保留自研 BM25 |
| 双写不一致 | 以 PG 为真相；提供 `reindex_weaviate` 一键修复 |
| Embedding 限流拖垮全量迁移 | 限速、断点、夜间跑批 |
| 运维负担从 Milvus 换到 Weaviate | compose 健康检查 + 备份策略写清 |
| 一次改太多 | 迁移期锁定切分与 embedding，只换存储与检索 |

---

## 11. 工作量粗估

| 阶段 | 人天（单人熟悉现仓） |
|---|---|
| Phase 0 准备 + 基线 | 0.5～1 |
| Phase 1 POC 双写 | 2～3 |
| Phase 2 读切换 | 1～2 |
| Phase 3 全量与下线 | 1 |
| **合计** | **约 5～7 人天**（含中文 BM25 踩坑缓冲） |

---

## 12. 建议决策

1. **先 Phase 0+1**：双写 + 同评测集对比，用数据决定是否全切。  
2. 若 hybrid/中文词面明显优于或持平现网，再 Phase 2～3。  
3. 若几乎无增益，可停止迁移，把人力转回 **文档 replace、切分优化、rerank**（往往性价比更高）。

---

## 13. 参考改动顺序（开发 checklist）

1. `VectorStore` 接口 + `weaviate_store.py`  
2. compose + settings  
3. ingest 双写 + delete_by_document  
4. retriever 读路径可切换  
5. 关闭默认内存 BM25  
6. 迁移脚本 `scripts/reindex_weaviate.py`  
7. eval 对比与 README  
8. 下线 Milvus  

文档版本：2026-09-04 | 对应现状：Milvus AUTOINDEX/HNSW_SQ + 内存 BM25 + PG chunks
