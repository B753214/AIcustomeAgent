# 基础设施依赖策略（Harness H0-4）

本文约定 **PostgreSQL / Milvus** 是否必选、启动与健康检查行为。以当前代码为准，不以「理想降级」为准。

---

## 1. 总表

| 依赖 | 是否必选 | 配置项 | 缺失时行为 |
|---|---|---|---|
| **PostgreSQL** | **必选** | `POSTGRES_URI`（无默认，须 `postgresql+asyncpg://...`） | **启动 fail-fast**：`lifespan` 无法 `init_db` 则进程起不来 |
| **Milvus** | **必选** | `MILVUS_URI`（默认 `http://localhost:19530`） | **启动 fail-fast**：`ensure_collection()` 连不上则起不来 |
| LLM / Embedding | 配置必填 | `AIROBOT_LLM_*` / `AIROBOT_EMBEDDING_*` | 配置阶段校验；运行时调用才真正连模型 |
| CrewAI | 可选 | `USE_CREW` + `requirements-extra` | 未装或失败 → LangChain 路由 |
| 重排 | 可选 | `RERANK_ENABLED` | 关闭则跳过 |
| 告警浏览器 | 可选降级链 | `ALARM_BROWSER_*` | MCP → Browser → 正文；可关浏览器 |
| 高德 MCP | 可选 | `AMAP_MCP_*` | 无 Key 则仅本地工具 |

**结论：本服务不做「无 PG / 无 Milvus 的内存降级」。**  
本地请 `docker compose up -d` 拉起 `postgres` + `milvus-standalone`，或自备等价实例。

---

## 2. 启动（lifespan）

顺序：

1. `init_db()` → 连 PostgreSQL，建表  
2. `ensure_collection()` → 连 Milvus，确保 collection  
3. 可选导入示例知识库 + `build_index()`（BM25 语料来自 PG）

任一步基础设施失败会抛出带明确文案的错误（见 `app/main.py` lifespan），避免静默半启动。

---

## 3. 健康检查 `GET /health`

| HTTP | 含义 |
|---|---|
| **200** | `postgres == ok` **且** `milvus == ok` |
| **503** | 任一必选依赖不可达 |

响应字段（兼容旧客户端）：

```json
{
  "status": "healthy | unhealthy",
  "postgres": "ok | unreachable: ...",
  "milvus": "ok | unreachable: ...",
  "dependencies": {
    "postgres": { "required": true, "status": "ok|unreachable" },
    "milvus": { "required": true, "status": "ok|unreachable" }
  },
  "llm_model": "...",
  "embedding_model": "..."
}
```

说明：`/health` **不**探测 LLM/Embedding 连通性（避免健康检查消耗额度）；模型名仅作信息展示。

---

## 4. 与文档中易混点的对齐

| 说法 | 是否成立 |
|---|---|
| 「Milvus 可选，可改用内存向量库」 | **不成立**（当前无内存向量后端） |
| 「可直接改 SQLite 不用 Postgres」 | **未实现**：FAQ 仅作自行改造提示；默认链路只支持 `asyncpg` |
| 「Crew / 重排 / 高德可选」 | **成立** |
| 「告警可无浏览器」 | **成立**（关 `ALARM_BROWSER_ENABLED` 或未装 Playwright） |

---

## 5. 本地推荐启动依赖

```powershell
# 仓库根目录
docker compose up -d postgres milvus-standalone
# 或一并起 API：
# docker compose up -d --build
```

确认：

```powershell
curl http://localhost:8000/health
```

期望 `"status":"healthy"` 且 postgres/milvus 均为 `ok`。

---

## 6. 验收（H0-4）

- [x] 文档写明 PG / Milvus **双必选**、无内存降级  
- [x] lifespan fail-fast 文案明确  
- [x] `/health` 与文档一致（双 ok → 200；否则 503 + required 标记）  
- [x] README FAQ / 前置条件与本文一致  
