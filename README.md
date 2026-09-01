# AI Custome Robort 智能客服

基于 **FastAPI + LangChain + Milvus + CrewAI** 构建的生产级智能客服服务，
支持意图识别路由、RAG 检索增强生成、多智能体协作、SSE 流式对话、语义缓存等核心能力。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-336791?logo=postgresql&logoColor=white)
![Milvus](https://img.shields.io/badge/Milvus-向量检索-blue)

---

## 目录

- [项目亮点](#项目亮点)
- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [接口文档](#接口文档)
- [配置说明](#配置说明)
- [项目结构](#项目结构)
- [常见问题](#常见问题)

---

## 项目亮点

| 能力 | 说明 | 对应模块 |
|------|------|----------|
| **意图路由** | LLM 分类为 knowledge / order / chat，自动选择处理链路 | `app/services/chat.py` |
| **RAG 知识库** | PDF/DOCX/MD/TXT 解析 → 分块 → 向量 + BM25 双路检索 → 重排 → 生成 | `app/rag/` |
| **多智能体** | CrewAI 双 Agent；工具：RAG/订单/天气/售后/告警 + 可选高德（Crew 包装）；失败降级 LangChain | `app/agents/crew.py` |
| **会话记忆** | PostgreSQL 持久化多轮对话，支持上下文追问 | `app/services/session_service.py` |
| **SSE 流式** | 闲聊：`astream_events` 推 tool stage + LLM token；RAG/告警亦支持流式 | `app/agents/chat_react.py` / `app/main.py` |
| **闲聊 Agent** | 手写 LangGraph `StateGraph`（`call_model` ⇄ `call_tools`）；工具：订单 / 本地天气 / 可选高德 MCP | `app/agents/chat_graph.py` |
| **语义缓存** | 首轮问题按余弦+词面双门限命中复用，毫秒级响应 | `app/services/semantic_cache.py` |
| **稳定性** | tenacity 指数退避重试 + 滑动窗口限流 | `app/services/resilience.py` / `ratelimit.py` |
| **可视化控制台** | 内置单页 Dashboard，实时监控全链路耗时 | `app/static/dashboard.html` |
| **告警排查** | info-plate 告警 RCA：MCP → 浏览器 → 正文；SSE `/api/analyze`；Crew Tool `investigate_alarm` | `app/agents/alarm/` |

---

## 系统架构

```
客户端（Web / 小程序 / 后端服务）
  │  POST /api/v1/chat | /chat/stream | /ingest
  ▼
FastAPI (app/main.py)
  │  ── 限流中间件（滑动窗口，按 IP）
  │  ── 请求日志中间件
  │
  ├─ CrewAI 可用 → 双 Agent（kickoff_async；订单/天气/可选高德/告警工具）
  │     ├─ 意图识别官 → 意图 JSON
  │     └─ 客服执行员 → 调用工具 → 生成答复
  │          ├─ search_knowledge（RAG）
  │          ├─ query_order / query_weather / maps_*（可选）
  │          ├─ after_sale_rule
  │          └─ investigate_alarm
  │
  └─ 降级 → LangChain 内置路由
        ├─ 意图分类 → knowledge / chat（含订单·天气工具）/ alarm
        ├─ chat → 手写 StateGraph（chat_graph）+ 可选高德 MCP
        └─ 语义缓存 → 重试 → 限流
        │
        └─ RAG 链路：
            文档解析 → 分块 → Embedding
            → 向量检索 + BM25 词面检索
            → RRF 融合 → 重排 → 生成
            │
            └─ 持久化：PostgreSQL 会话 + Milvus 向量
```

**闲聊链路（Chat-SG，已替代预置 `create_agent`）：**

```
intent=chat
  → run_chat_react / iter_chat_react
  → StateGraph: call_model ⇄ call_tools → END
  → 本地工具：query_order、query_weather
  → 可选：AMAP_MCP_ENABLED + Key → maps_*（langchain-mcp-adapters）
  → SSE：stage(tool) + on_chat_model_stream token + result
```
**一次对话时序（非流式）：**

```
客户端 → 限流中间件 → 语义缓存检查
      → 意图分类（LLM）
      → 执行（knowledge: 混合检索 + RAG 生成）
      → 写会话 + 写缓存
      → 200 JSON 返回
```

---

## 技术栈

| 层 | 组件 | 说明 |
|----|------|------|
| Web 框架 | FastAPI + uvicorn + Pydantic | 异步接口、自动 OpenAPI 文档 |
| 数据库 | PostgreSQL + SQLAlchemy（asyncpg） | 会话持久化 |
| 向量库 | Milvus（pymilvus） | 向量 ANN 检索 |
| LLM 编排 | LangChain + **LangGraph** | 意图/RAG；闲聊手写 StateGraph |
| 多智能体 | CrewAI（Agent/Task/Crew） | 可选，未安装自动降级 |
| MCP（可选） | langchain-mcp-adapters | 高德地图工具；`AMAP_MCP_ENABLED` |
| 文档解析 | pypdf + python-docx | PDF / Word 解析 |
| 检索 | jieba + rank_bm25 | BM25 中文词面检索 |
| 稳定性 | tenacity | 指数退避重试 |
| 重排 | sentence-transformers bge-reranker | 可选，懒加载 |

---

## 快速开始

### 前置条件

- Python **3.10 - 3.12**
- PostgreSQL 数据库
- Milvus 向量库（可选，不用则默认用内存存储）
- 一个 OpenAI 兼容的 LLM 服务（DashScope / Ollama / DeepSeek）

### 1. 克隆 & 安装依赖

```powershell
git clone <repo-url>
cd AICustomeRobort

python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 核心依赖
pip install -r requirements.txt

# 可选：多智能体 + 重排 + 告警浏览器降级（Playwright）
pip install -r requirements-extra.txt

# 启用浏览器降级时再装 Chromium
playwright install chromium
```

### 2. 配置环境变量

```powershell
Copy-Item .env.example .env
```

按实际情况编辑 `.env`，关键配置项：

```ini
# 大模型（必选）
AIROBOT_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AIROBOT_LLM_API_KEY=your-api-key
AIROBOT_LLM_MODEL=qwen-plus

# 向量模型（必选）
AIROBOT_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AIROBOT_EMBEDDING_API_KEY=your-api-key
AIROBOT_EMBEDDING_MODEL=text-embedding-v4

# PostgreSQL（必选）
POSTGRES_URI=postgresql://user:password@localhost:5432/airobot

# Milvus（可选，默认用内存存储）
AIROBOT_MILVUS_URI=http://localhost:19530
```

> **本地 Ollama 示例（免费离线）：**
> ```ini
> AIROBOT_LLM_BASE_URL=http://localhost:11434/v1
> AIROBOT_LLM_API_KEY=ollama
> AIROBOT_LLM_MODEL=qwen2.5:1.5b
> AIROBOT_EMBEDDING_BASE_URL=http://localhost:11434/v1
> AIROBOT_EMBEDDING_API_KEY=ollama
> AIROBOT_EMBEDDING_MODEL=nomic-embed-text
> ```
> ```powershell
> ollama pull qwen2.5:1.5b
> ollama pull nomic-embed-text
> ```

### 3. 启动服务

Windows 若因控制台编码（emoji/中文）启动失败，先设置 UTF-8：

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. 验证

```powershell
# 健康检查
Invoke-RestMethod http://localhost:8000/health

# 知识问答
$body = @{ message = "怎么申请退款？"; session_id = "user-001" } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/api/v1/chat -Method Post -Body $body -ContentType "application/json"

# 可视化控制台（浏览器访问）
# http://localhost:8000/dashboard
```

---

## 接口文档

启动后访问 <http://localhost:8000/docs> 查看 Swagger UI 自动生成的交互式 API 文档。

### `POST /api/v1/chat` — 智能对话

请求体：
```json
{
  "message": "退货运费谁承担？",
  "session_id": "user-001"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| message | string | 是 | 用户消息 |
| session_id | string | 否 | 会话标识，默认 `default` |

响应：
```json
{
  "reply": "根据平台规则，因商品质量问题或与描述不符导致的退货，运费由卖家承担；买家个人原因退货则由买家承担。",
  "intent": "knowledge",
  "sources": ["knowledge_base.md#4"],
  "engine": "langchain",
  "used_crew": false,
  "cache_hit": false
}
```

| 字段 | 说明 |
|------|------|
| reply | 客服回答 |
| intent | knowledge / order / chat / crew |
| sources | RAG 来源列表（`文件#分块号`） |
| engine | langchain / crew |
| used_crew | 本次是否实际走 CrewAI |
| cache_hit | 是否命中语义缓存 |

### `POST /api/v1/chat/stream` — SSE 流式对话

响应为 `text/event-stream`，按以下事件序列推送：

```
data: {"type":"stage","stage":"intent","msg":"意图=knowledge"}
data: {"type":"intent","intent":"knowledge"}
data: {"type":"token","content":"根据平台规则，"}
data: {"type":"token","content":"因商品质量问题..."}
...
data: {"type":"done","reply":"...","intent":"knowledge"}
```

事件类型说明：

| type | 说明 |
|------|------|
| `stage` | 阶段状态（意图识别/检索/生成等） |
| `intent` | 意图分类结果 |
| `token` | 逐 token 输出的内容 |
| `done` | 完成，携带最终回复和元数据 |

### `POST /api/v1/ingest` — 上传文档入库

```powershell
curl -X POST http://localhost:8000/api/v1/ingest -F "file=@data/knowledge_base.md"
```

支持 `.pdf / .docx / .md / .txt / .markdown`

响应：
```json
{"file_name": "knowledge_base.md", "chunks": 7, "total_chunks": 14}
```

### `GET /health` — 健康检查

```json
{
  "status": "healthy",
  "postgres": "ok",
  "milvus": "ok",
  "llm_model": "qwen-plus",
  "embedding_model": "text-embedding-v4"
}
```

### `GET /dashboard` — 可视化控制台

浏览器访问，实时展示全链路耗时与状态。

### `POST /api/analyze` — 告警分析（SSE）

供独立工作台对接。请求体提供 `content` 或 `url`（info-plate 链接，或自然语言如 `configId=11664 最近1小时`）。

```json
{ "content": "https://info-plate.fc.alibaba-inc.com/monitor/searchall?marketConfigId=11664&bizType=30" }
```

事件类型：`progress` / `chunk` / `done`（含 `report`、`meta`）/ `error`，结束为 `data: [DONE]`。

拉数顺序固定：**MCP → Playwright 浏览器 → 告警正文降级**（无需再配 fetch mode）。浏览器登录也可调 `GET/POST /login`。

> 钉钉推送与 React 工作台静态托管不在本仓库；前端自行将 API baseURL 指向本服务即可。

---

## 配置说明

| 变量 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `AIROBOT_LLM_BASE_URL` | str | — | 大模型 API 地址 |
| `AIROBOT_LLM_API_KEY` | str | — | 大模型 API Key |
| `AIROBOT_LLM_MODEL` | str | — | 大模型名称 |
| `AIROBOT_EMBEDDING_BASE_URL` | str | — | 向量模型 API 地址 |
| `AIROBOT_EMBEDDING_API_KEY` | str | — | 向量模型 API Key |
| `AIROBOT_EMBEDDING_MODEL` | str | — | 向量模型名称 |
| `POSTGRES_URI` | str | — | PostgreSQL 连接字符串 |
| `AIROBOT_MILVUS_URI` | str | `http://localhost:19530` | Milvus 地址 |
| `AIROBOT_USE_CREW` | bool | `false` | 启用 CrewAI（订单/天气/可选高德/`investigate_alarm`）；需 `requirements-extra.txt` |
| `ALARM_MCP_ENABLED` | bool | `true` | 告警是否先走 MCP |
| `ALARM_MCP_TOKEN` | str | — | info-plate MCP token；空则跳过 MCP |
| `ALARM_BROWSER_ENABLED` | bool | `true` | MCP 失败后是否 Playwright 降级 |
| `ALARM_INFO_PLATE_USER` / `PASSWORD` | str | — | 浏览器登录账号 |
| `ALARM_REPORT_FORMAT` | str | `markdown` | `markdown` \| `rca` |
| `ALARM_SKIP_WHEN_ZERO_COUNT` | bool | `true` | 监控 count=0 时跳过 LLM |
| `AMAP_MCP_ENABLED` | bool | `false` | 闲聊是否加载高德 MCP 工具 |
| `AMAP_MAPS_API_KEY` | str | — | 高德 Key（仅 `.env`，勿提交仓库） |
| `AMAP_MCP_URL` | str | `https://mcp.amap.com/mcp` | 高德 MCP 地址 |
| `AIROBOT_TOP_K` | int | — | 检索召回条数 |
| `AIROBOT_CHUNK_SIZE` | int | — | 文档分块大小 |
| `AIROBOT_CHUNK_OVERLAP` | int | — | 分块重叠大小 |
| `AIROBOT_RETRY_ATTEMPTS` | int | `3` | 重试次数 |
| `AIROBOT_RETRY_MAX_WAIT` | int | `3` | 最大退避秒数 |
| `AIROBOT_RATELIMIT_ENABLED` | bool | `true` | 是否启用限流 |
| `AIROBOT_RATELIMIT_PER_MINUTE` | int | `30` | 每分钟最大请求数 |
| `AIROBOT_CACHE_ENABLED` | bool | `true` | 是否启用语义缓存 |
| `AIROBOT_CACHE_THRESHOLD` | float | `0.75` | 缓存余弦相似度阈值 |
| `AIROBOT_CACHE_LEXICAL_THRESHOLD` | float | `0.5` | 缓存词面重叠阈值 |

---

## 项目结构

```
AICustomeRobort/
├── app/
│   ├── main.py              # FastAPI 入口：接口/中间件/SSE
│   ├── config.py             # 环境变量配置（Pydantic Settings）
│   ├── schemas.py           # 请求/响应 Pydantic 模型
│   ├── database.py          # SQLAlchemy async 引擎
│   ├── agents/
│   │   ├── chat_graph.py    # 闲聊手写 StateGraph（主循环）
│   │   ├── chat_react.py    # 闲聊入口 run_/iter_（SSE token）
│   │   ├── weather.py       # 本地天气工具
│   │   ├── amap_mcp.py      # 高德 MCP：LC tools + Crew 同步壳
│   │   ├── crew.py          # CrewAI（kickoff_async；对齐闲聊工具）
│   │   ├── tools.py         # Crew 工具集（RAG/订单/天气/售后/告警）
│   │   └── alarm/           # 告警 Agent（detect/fetch/playbook/RCA/SSE）
│   ├── rag/
│   │   ├── loader.py        # PDF/DOCX/MD 文档解析
│   │   ├── retriever.py     # RAG 检索+生成主链路
│   │   ├── milvus_store.py  # Milvus 向量存储
│   │   ├── fusion.py        # RRF 融合
│   │   ├── lexical.py       # jieba + BM25 词面检索
│   │   └── reranker.py      # bge-reranker 语义重排
│   ├── services/
│   │   ├── chat.py          # 编排层：意图路由 + 双通道输出
│   │   ├── resilience.py    # tenacity 重试
│   │   ├── ratelimit.py     # 滑动窗口限流
│   │   ├── semantic_cache.py # 语义缓存
│   │   ├── session_service.py # 会话持久化
│   │   └── chunk_service.py # 分块入库
│   ├── models/              # SQLAlchemy ORM 模型
│   └── static/dashboard.html # 可视化控制台
├── data/                    # 知识库文件
├── tests/                   # 单元测试
├── plan/                    # 实施计划文档
├── .env.example             # 环境变量模板
├── docker-compose.yml       # Docker 部署编排
├── requirements.txt         # 核心依赖
├── requirements-extra.txt  # 可选：CrewAI + 重排
└── requirements-dev.txt    # 开发/测试依赖
```

---

## 常见问题

**Q：未配置 API Key 能跑吗？**
能。服务可启动，`/health` 正常，但对话接口会返回"未配置 AIROBOT_LLM_API_KEY"提示。

**Q：没有 PostgreSQL 怎么办？**
可临时用 SQLite 替代，修改 `POSTGRES_URI=sqlite+aiosqlite:///./airobot.db`，但生产推荐 PostgreSQL。

**Q：没有 Milvus 怎么办？**
项目支持内存存储（`InMemoryVectorStore`），数据仅在运行期间有效，重启会丢失。

**Q：crewai 没装会怎样？**
自动降级到 LangChain 内置路由；告警在 `USE_CREW=false` 时也可经启发式/旁路进入 `alarm` Agent，不依赖 Crew。

**Q：告警浏览器降级报错 / 找不到 chromium？**
先 `pip install -r requirements-extra.txt`，再执行 `playwright install chromium`。也可设 `ALARM_BROWSER_ENABLED=false`，仅用 MCP + 正文。

**Q：还需要部署 car_robot（Node）吗？**
排查链路（chat 告警旁路 + `/api/analyze`）已在本仓库 Python 内闭环，可不部署 Node。钉钉 Webhook / 原 React 工作台仍可用原 `car_robot` 或独立前端。

**Q：如何接入真实订单系统？**
修改 `app/agents/tools.py` 中的 `query_order` 函数，改为 HTTP 调用真实订单服务。

**Q：前端如何对接流式接口？**
```javascript
// EventSource 只支持 GET，推荐用 fetch：
const response = await fetch('/api/v1/chat/stream', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({message, session_id})
});
const reader = response.body.getReader();
// 解析 SSE data: {...} 事件
```

---

## License

MIT License