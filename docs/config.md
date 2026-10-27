# 配置字段对照表（Harness H0-3）

## SSE 心跳

`SSE_HEARTBEAT_INTERVAL_SEC`：默认 `15` 秒，必须大于 0。聊天流（含旧分支）与告警分析流在建立连接时发送 `: heartbeat\n\n`，等待业务事件时按此间隔补发心跳。正常业务数据到达后重新计算空闲间隔。

心跳是 SSE 注释，不展示、不作为 Agent 事件落库；前端收到字节后会重置 120 秒无数据超时。心跳不代表任务取得进展，也不替代模型、工具或任务总时限。客户端断开时会取消待取事件并关闭生成器，远端调用能否立即停止仍取决于外部服务。

与 `app/config.py`、`.env.example` 保持同步。  
环境变量名与字段名对应（**大小写不敏感**）；不要给无前缀字段乱加 `AIROBOT_`（例如用 `USE_CREW`，不要写成 `AIROBOT_USE_CREW`）。

复制示例：

```powershell
Copy-Item .env.example .env
```

缺必填项时，导入 `app.config` 会抛出带字段列表的 `RuntimeError`（见 `get_settings()`）。

PostgreSQL / Milvus 是否必选与健康检查语义见 [deps.md](./deps.md)。

---

## 1. 必填（无默认值，启动前必须有）

| 环境变量 | Settings 字段 | 说明 |
|---|---|---|
| `AIROBOT_LLM_BASE_URL` | `AIROBOT_LLM_BASE_URL` | OpenAI 兼容 LLM Base URL |
| `AIROBOT_LLM_API_KEY` | `AIROBOT_LLM_API_KEY` | LLM API Key |
| `AIROBOT_LLM_MODEL` | `AIROBOT_LLM_MODEL` | 主对话 / RAG / 告警模型名 |
| `AIROBOT_LLM_LIGHT_MODEL` | `AIROBOT_LLM_LIGHT_MODEL` | 轻量模型（意图分类、检索改写、会话摘要、事实抽取）；默认 `qwen-turbo` |
| `AIROBOT_EMBEDDING_BASE_URL` | `AIROBOT_EMBEDDING_BASE_URL` | Embedding Base URL |
| `AIROBOT_EMBEDDING_API_KEY` | `AIROBOT_EMBEDDING_API_KEY` | Embedding Key |
| `AIROBOT_EMBEDDING_MODEL` | `AIROBOT_EMBEDDING_MODEL` | Embedding 模型名 |
| `POSTGRES_URI` | `POSTGRES_URI` | 须 `postgresql+asyncpg://...` |
| `TOP_K` | `top_k` | 检索返回条数 |
| `CHUNK_SIZE` | `chunk_size` | 默认分块大小 |
| `CHUNK_OVERLAP` | `chunk_overlap` | 分块重叠 |

---

## 2. 有默认值（可省略）

### 兼容别名

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `embedding_base_url` / `embedding_api_key` / `embedding_model` | 空 → 回落 `AIROBOT_EMBEDDING_*` | 历史兼容；一般不必再填 |
| `PROVIDER` | `openai` | `init_chat_model` 的 provider |

### 存储 / RAG

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `MILVUS_URI` | `http://localhost:19530` | Milvus 地址 |
| `COLLECTION_NAME` | `customer_milvus_collection` | Collection 名 |
| `DIM` | `1024` | 向量维度 |
| `PDF_CHUNK_SIZE` / `PDF_CHUNK_OVERLAP` | `800` / `80` | PDF 分块 |
| `PDF_SECTION_MAX_CHARS` / `MIN` | `1000` / `150` | PDF 结构切分 |
| `HYBRID_*` | 开启，topk=20 | 混合检索 |
| `RERANK_*` | 关闭 | 重排；开启需 extra 依赖 |

### 会话 / 稳定性 / API

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `USE_CREW` | `false` | CrewAI 可选路径 |
| `CREW_TOOLS_READY` | `true` | 工具就绪标记 |
| `MEMORY_MAX_TURNS` | `5` | 短时记忆轮数 |
| `MEMORY_CONTEXT_TOKEN_BUDGET` | `3000` | Chat 历史上下文软预算 |
| `RAG_HISTORY_TOKEN_BUDGET` | `6000` | Knowledge 按会话读取历史时使用的独立软预算 |
| `RAG_RUN_TOKEN_BUDGET` | `16000` | Knowledge Harness 累计模型 Token 预算，含模型输入和输出；保持 Chat 的 8000 不变 |
| `RETRY_ATTEMPTS` / `RETRY_MAX_WAIT` | `3` / `3` | tenacity |
| `TOOL_TIMEOUT_SEC` | `30` | 单次工具超时 |
| `ORDER_MOCK_FAIL_RATE` | `0` | Mock 订单失败概率；离线测试保持 0 |
| `RATELIMIT_*` | 开 / 30 | IP 限流 |
| `CACHE_*` / `MAX_ENTRIES_CACHE` | 开 | 语义缓存 |
| `API_KEY_ENABLED` / `SERVICE_API_KEY` | 关 / 空 | 服务 API Key |
| `DEBUG` / `APP_VERSION` | `true` / `0.1.0` | 调试与版本 |

### 告警 / 高德

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `ALARM_MCP_*` | 见 `.env.example` | MCP 拉数 |
| `ALARM_BROWSER_*` / `ALARM_INFO_PLATE_*` | 见示例 | Playwright 降级 |
| `ALARM_REPLAN_*` / `ALARM_REPORT_*` | 见示例 | Replan / 报告 |
| `ALARM_REPLAN_ENABLED` | `true` | LLM 判断首批证据是否足够；false 时只分析首批 |
| `ALARM_REPLAN_TIMEOUT_SEC` | `30` | 单次证据评估超时（秒） |
| `ALARM_REPLAN_TIME_BUDGET_SEC` | `60` | 证据评估及补页的总时间预算（秒），不含首次抓取和最终报告 |
| `AMAP_*` / `WEATHER_API_KEY` | 关 / 空 | 闲聊地图与天气 |

---

## 3. 常见误命名（不要这样写）

| 错误 | 正确 |
|---|---|
| `AIROBOT_USE_CREW` | `USE_CREW` |
| `AIROBOT_MILVUS_URI` | `MILVUS_URI` |
| `AIROBOT_TOP_K` | `TOP_K` |
| `AIROBOT_POSTGRES_URI` | `POSTGRES_URI` |

---

## 4. 验收（H0-3）

- [x] `.env.example` 覆盖 Settings 中对外配置项
- [x] 必填 / 可选在本文区分清楚
- [x] `embedding_*` 不再强制双填
- [x] 缺项时有可读错误（含字段名）
