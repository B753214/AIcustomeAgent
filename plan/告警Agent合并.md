# 告警 Agent 合并计划（car_robot → AICustomeRobort）

跟做方式与 [分步实施.md](./分步实施.md) 相同：**你写代码，我带练审 diff，不代写完整实现**。  
对话里说：**「开始 Alarm-DayN」**（或「开始 DayN」）。

关联仓库：

- 客服主项目：`AICustomeRobort`（目标宿主）
- 告警 Node 服务：`car_robot`（`fc_monitor.js`，对照实现；**迁完后不再作为运行时依赖**）

---

## 一、结论摘要

| 问题 | 答案 |
|------|------|
| car_robot 是单独 Agent 吗？ | 是单独的**告警排查服务**，不是 CrewAI Agent |
| 怎么合并？ | **核心迁入 Python**：解析 / 分类 / playbook / LLM / 拉数（MCP+浏览器）/ `/api/analyze` SSE |
| 还依赖 Node 侧车吗？ | **目标是不依赖**（排查链路）。Day1–8 已完成核心；Day9–11 补齐报告与收尾 |
| CrewAI 怎么可达？ | Tool `investigate_alarm` → 同一 `run_alarm_agent` |

**明确不做（不迁）：**

- 钉钉推送 / Outgoing Webhook / `/alert` / `sendToDingTalk` / 引用消息
- React 工作台静态托管（`serveStatic`）；前端继续独立部署，改 API `baseURL` 即可

**一套核心，三条入口：**

| 入口 | 行为 | 状态 |
|------|------|------|
| `use_crew=false` + `/api/v1/chat` | 意图 `alarm` → `run_alarm_agent` | ✅ Day2–7 |
| `use_crew=true` | Router → Tool `investigate_alarm` | ✅ Day6 |
| **`POST /api/analyze`** | SSE 流式报告 | ✅ Day5（NL 抽链见 Day10） |

---

## 二、欠缺功能清单（对照 `fc_monitor.js`）

> Day1–8 已完成项不再展开。下表为**仍待迁移**或**明确不做**。

| 优先级 | 能力 | Node 对照 | Python 现状 | 计划 |
|--------|------|-----------|-------------|------|
| **P0** | MCP 失败 → 浏览器拉数 | `fetchPageData`、`login` | ✅ Day8 | 已完成 |
| **P1** | 五类 Skill Playbook | `SKILL_PLAYBOOKS` | 仅 `generic.md` | **Day9** |
| **P1** | 完整 Markdown 报告 | `buildUrlReport` | 仅 RCA 纯文本 | **Day9** |
| **P1** | 规则错误分析 | `analyzeErrorDetails` | 无 | **Day9** |
| **P1** | 零失败短路 | `count === 0` → skip | 仍调 LLM | **Day9** |
| **P1** | Playbook 截断 | `truncatePlaybook` | 无 | **Day9** |
| **P2** | 无 URL 自然语言抽链 | `CHAT_SYSTEM_PROMPT` | 必须有 content/url | **Day10** |
| **清理** | 侧车 HTTP 空壳 | — | `client.py` stub | **Day11 删除** |
| **不做** | 钉钉推送 / webhook / `/alert` | `sendToDingTalk` 等 | — | **不做** |
| **不做** | React 静态托管 | `serveStatic` | — | **不做** |
| **不做** | ngrok 公网回调提示 | startup | — | **不做** |

浏览器 SMS/扫码：Day8 登录失败即降级；`/sms` 不单独迁移（无钉钉场景）。

**已知策略差异（非 bug）：**

- 启发式 `is_alarm_message`：Python 要求 **字段 + 监控链接**；Node 为字段 **或** URL。
- 报告格式：Day9 对齐 Markdown 模板；对外仍以 `/api/analyze` / `/chat` 消费，不接钉钉。

---

## 三、目标架构（目标态）

```
用户消息 / 监控 URL
  → 语义缓存（alarm 不写缓存）
  → 启发式检测（字段 ∧ 链接 → 强 alarm）
       ├─ 命中 → run_alarm_agent
       └─ 未命中 → Crew 或 classify_intent

run_alarm_agent / stream
  → parse / classify / playbook（Day9 五类 skill）
  → MonitorFetcher
       ├─ MCP（优先）
       ├─ Browser（Day8）
       └─ text_fallback
  → analyzeErrorDetails（Day9）
  → LLM（RCA）
  → buildUrlReport（Day9 完整 md，供 SSE/chat）

POST /api/analyze
  → 有 URL/configId → 上述 core 流式
  → 无 URL → chatWithLLM 抽 analyze action（Day10）→ 再进 core
  → SSE：progress / chunk / done / error + [DONE]
```

### 目录约定（目标态）

```
app/agents/alarm/
  detect.py
  parse.py
  classify.py
  mcp.py
  browser.py          # Day8 ✅
  fetcher.py
  format.py           # Day9：format_detail、truncate_playbook
  report.py           # Day9：analyze_error_details、build_url_report
  chat_intent.py      # Day10：无 URL 时抽 analyze JSON
  runner.py
  playbooks/
    generic.md
    ajx.md | bff.md | render.md | voc.md | precise.md   # Day9
app/agents/tools.py
app/services/chat.py
```

**删除**：`client.py`（侧车 HTTP，Day11）。

### 配置项（汇总）

```text
# MCP（已有）
alarm_mcp_enabled / alarm_mcp_host / alarm_mcp_path / alarm_mcp_token
alarm_mcp_timeout_sec / alarm_mcp_verify_ssl

# 浏览器（Day8 ✅）
alarm_browser_enabled / alarm_browser_profile_dir
alarm_info_plate_user / alarm_info_plate_password
alarm_browser_timeout_sec / alarm_browser_headless

# 报告（Day9）
alarm_skip_when_zero_count: bool = True
alarm_report_format: str = "rca"   # rca | markdown
```

拉数策略（固定，无 mode 开关）：`MCP →（失败）Browser → text_fallback`。  
无 token / MCP 关 → 直接尝试浏览器（若 `alarm_browser_enabled`）；浏览器也关或失败 → 正文降级。  
`meta.fetch_channel`：`mcp` | `browser` | `text_fallback`。

---

## 四、计划表（Day1–11）

| ID | 主题 | 你交付 | 过关标准 | 对照 |
|----|------|--------|----------|------|
| **Day1–7** | 核心链路 | 见进度勾选 | 已验收 | — |
| **Day8** | 浏览器降级 | `browser.py` + fetcher + `/login` | MCP→browser→降级 | `fetchPageData` ✅ |
| **Day9** | **Playbook + 报告** | 五类 md + `report.py` + `format.py` | Markdown；规则证据；count=0 skip | `buildUrlReport` |
| **Day10** | **NL 抽链** | `chat_intent.py` + analyze | 无 URL 可构造链接再分析 | `CHAT_SYSTEM_PROMPT` |
| **Day11** | **收尾** | 删 `client.py`；文档；单测 | 清单闭合；README | — |

建议顺序：**Day9 → Day10 → Day11**。

---

## 五、Day5 / Day8 细节

Day5（MCP + `/api/analyze`）、Day8（浏览器）已实现，备查见代码：`mcp.py` / `fetcher.py` / `browser.py` / `runner.py`。

Day8 SMS/扫码：登录失败 → `text_fallback`（不迁 `/sms`、不接钉钉通知）。

---

## 六、Day9 细节（Playbook + 报告形态）

对照：**670–692**、**816–833**、**932–1022**、**1480–1485**。

### 6.1 Playbook

- 五份 `playbooks/{ajx,bff,render,voc,precise}.md`
- `truncate_playbook(text, max_len=3000)`

### 6.2 `report.py`

```python
def analyze_error_details(detail_data) -> dict: ...
def build_url_report(rate_data, error_analysis, monitor_url, ai_result, *, channel: str) -> str: ...
def should_skip_analysis(rate_data) -> str | None: ...
```

- `/api/analyze` 的 `done.report` 可出完整 Markdown
- `alarm_report_format=rca|markdown` 可切换

### 6.3 过关

- [ ] BFF → 加载 `bff.md`
- [ ] 报告含监控名/次数/证据/建议/链接
- [ ] `count=0` → skip 或短报告

---

## 七、Day10 细节（自然语言抽监控链）

对照：**1159–1174**、**/api/analyze 1400–1428**。

### 7.1 `chat_intent.py`

```python
async def resolve_analyze_url(content: str) -> tuple[str | None, str | None]:
    """(url, chat_reply)。有 url 则拉数；仅闲聊则 chat_reply 非空。"""
```

### 7.2 `/api/analyze`

```text
无 URL → progress「正在理解你的问题...」
  → resolve_analyze_url → 有 url 则 core；否则闲聊 done
```

### 7.3 过关

- [x] 「configId=11664 最近1小时」→ 构造 URL 并 RCA（依赖 LLM；解析单测已覆盖）
- [x] 纯闲聊 → done.report，不 500（链路已接；无 URL 走 resolve）

---

## 八、Day11 细节（收尾）

### 8.1 必做

- [x] 删除 `app/agents/alarm/client.py`
- [x] `.env.example` / README（`playwright install`、`USE_CREW`、UTF-8）
- [x] 单测：`report.py`、`chat_intent.py`（mock）

### 8.2 可选

- [ ] 启动时 `ensure_logged_in()` 预登录（未做；可用 `GET/POST /login`）
- [ ] 进程内最近告警调试缓存（非钉钉）

### 8.3 完成定义

- [x] 排查链路可不部署 `car_robot` Node
- [x] Day1–11 打勾；总验收通过
- [x] **钉钉 / 前端工作台仍可用原 car_robot 或独立前端**（本项目不迁）

---

## 九、打勾进度

- [x] Alarm-Day1 检测 + 意图
- [x] Alarm-Day2 无 Crew 旁路
- [x] Alarm-Day3 parse / classify / playbook
- [x] Alarm-Day4 runner + LLM
- [x] Alarm-Day5 MCP + `/api/analyze`
- [x] Alarm-Day6 CrewAI Tool
- [x] Alarm-Day7 SSE / UI / 单测 / 总验收
- [x] Alarm-Day8 浏览器降级
- [x] Alarm-Day9 Playbook + 报告形态
- [x] Alarm-Day10 NL 抽链
- [x] Alarm-Day11 收尾（删 client、文档、单测）
- [x] ~~钉钉 Webhook~~ → **不做**
- [x] ~~React 静态托管~~ → **不做**

---

## 十、总验收

1. 客服：FAQ → `knowledge`；订单 → `order`；闲聊 → `chat`
2. 告警（字段+链接）：`intent=alarm`，`engine=alarm`
3. Crew：`investigate_alarm` 出 RCA
4. 拉数三级：**MCP → browser → 正文**，全程不 500
5. `/api/analyze` SSE 兼容；无 URL 时可 NL 抽链（Day10）
6. 报告：Markdown + 规则证据（Day9）；`count=0` 可 skip
7. 五类 playbook 按指标名加载
8. 告警不进语义缓存
9. **不部署 car_robot Node** 仍可完成告警排查闭环（不含钉钉推送）

---

## 十一、带练约定

1. 你说：**「开始 Alarm-DayN」**。  
2. 我只给：目标、必改文件、签名/伪代码、对照 JS、过关命令——**不代写完整实现**。  
3. 你本地写完，贴关键代码或报错。  
4. 我审过关后勾进度，再进下一天。

卡住时发：`Alarm-DayN` + 文件路径 + 报错原文。
