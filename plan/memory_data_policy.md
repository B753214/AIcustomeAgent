# 记忆数据策略（Memory-M0-2）

> 对应 [记忆系统跟做计划.md](./记忆系统跟做计划.md) M0-2。  
> 对齐 H6 [`DataPolicy`](../app/harness/policies/data.py)：实现挂钩在 **M2-4**，本文只定规则。  
> 分类边界见 [memory_taxonomy.md](./memory_taxonomy.md)。

---

## 1. 三档处置

| 档位 | 含义 | 典型动作 |
|------|------|----------|
| **允许原文** | 可进对应存储 | 正常写入 |
| **允许但脱敏** | 可进，须先打码/截断 | 走与 `DataPolicy` 一致的 `mask` / 摘要 |
| **禁止** | 不得进入该存储 | 丢弃、改写为占位符、或仅留「已省略」 |

---

## 2. 按记忆层：允许记什么

| 层 | 允许 | 禁止 |
|----|------|------|
| **Short-term**（会话消息） | 用户问题、助手回答、业务可见的告警报告正文（脱敏后） | 明文密钥、完整 Cookie、密码；工具原始密钥参数 |
| **Summary** | 主题、稳定事实、决策、未决问题（结构化、无密钥） | 把密钥/Token 写进摘要；用猜测冒充「已知事实」 |
| **Episodic**（`last_alarm_episode`） | `config_id`、监控 URL（必要时去 query 密钥）、页码、证据**摘要**、playbook 提示、`source_run_id` | 浏览器 Cookie、登录密码、完整抓取原文若含敏感头 |
| **Execution**（checkpoint） | 步骤名、可恢复业务 payload、幂等键 | 用户长期偏好；完整聊天历史；跨轮追问名片（那是 Episodic） |
| **Semantic**（长期事实，M4） | 用户**显式**偏好/约束、经确认的稳定业务事实 | 天气、单次订单状态、纯模型推断、敏感证件号 |
| **Cache** | 无个性化、可共享的 knowledge 类问答结果（且已脱敏） | 订单/天气/告警/含 user 私有内容的回答；跨用户共用同一条目 |
| **Run/Events** | 脱敏后的 input/output/事件 payload | 与 DataPolicy 冲突的明文敏感串 |

---

## 3. 字段级策略表（≥8 类）

| # | 字段/模式 | Short-term | Summary | Episodic | Semantic | Cache | Trace/Run/Event | 处置 |
|---|-----------|:---:|:---:|:---:|:---:|:---:|:---:|------|
| 1 | `sk-*` / LLM API Key | 脱敏 | 禁 | 禁 | 禁 | 禁 | 脱敏 | 对齐 DataPolicy `sk_key` |
| 2 | `password` / `passwd` / `pwd=` | 脱敏 | 禁 | 禁 | 禁 | 禁 | 脱敏 | DataPolicy `password` |
| 3 | `api_key` / `api_secret` | 脱敏 | 禁 | 禁 | 禁 | 禁 | 脱敏 | DataPolicy `api_key` |
| 4 | `access_token` / `auth_token` / `secret_key` | 脱敏 | 禁 | 禁 | 禁 | 禁 | 脱敏 | DataPolicy `token` |
| 5 | `Bearer …` | 脱敏 | 禁 | 禁 | 禁 | 禁 | 脱敏 | DataPolicy `bearer` |
| 6 | 私钥 PEM 块 | 禁/脱敏 | 禁 | 禁 | 禁 | 禁 | 脱敏 | DataPolicy `private_key` |
| 7 | Cookie / `Set-Cookie` / `.browser_profile` 会话 | 禁 | 禁 | 禁 | 禁 | 禁 | 禁 | 不得进记忆与 Trace 正文 |
| 8 | 手机号 | 脱敏或禁 | 禁入长期 | 一般禁 | 禁（除非显式且合规） | 禁 | 脱敏 | **DataPolicy 尚未覆盖，M2-4 需补规则** |
| 9 | 身份证 / 护照号 | 禁 | 禁 | 禁 | 禁 | 禁 | 禁或强脱敏 | 同上，优先禁止落库 |
| 10 | 告警 URL 中的敏感 query（token、签名、ticket） | 脱敏 URL | 禁原文 | URL **去敏感 query** 后可存 | 禁 | 禁 | 脱敏 | Episodic 只留可公开定位所需参数 |
| 11 | info-plate 账号密码（配置项） | 禁 | 禁 | 禁 | 禁 | 禁 | 禁 | 仅存配置环境，不进会话/episode |
| 12 | 工具参数中的密钥类字段 | metadata 只留工具名+脱敏摘要 | 禁明细 | 禁 | 禁 | 禁 | 脱敏 | 明细优先看 harness events（已 sanitize） |
| 13 | 临时天气 / 单次物流状态 | 可进 Short-term | 摘要可提「查过天气」勿当事永久实 | 一般不进 | **禁** | 看策略，偏禁共享 | 可 | Semantic 硬禁止 |
| 14 | 模型猜测的「用户偏好」 | 可当回复 | 勿当 known_facts | — | 仅 `candidate`，须确认 | 禁当偏好缓存 | — | 显式优先于推断 |

说明：表中「脱敏」= 写入前调用与 H6 相同的打码逻辑（或共享 `DataPolicy.mask_str` / `sanitize`）。

---

## 4. 与现有 DataPolicy 的缺口

当前 `DataPolicy` 默认已覆盖：

- `sk_key`、`password`、`api_key`、`token`、`bearer`、`private_key`

**记忆写入路径尚未统一走该策略**（会话 `content`/`metadata`、摘要、episode、Cache put）。

M2-4 建议补齐：

1. 会话 `save_turn` / metadata / episode / summary 写入前 `sanitize`  
2. 增加：手机号、身份证、Cookie 头、URL query 中的 `token|sign|ticket`（可配置）  
3. Cache `put` 前对 `result` 打码，且 key 带 user scope（M7-1）

---

## 5. Semantic 写入门槛（预告 M4，本步只定规矩）

| source_type | 条件 | 初始 status |
|-------------|------|-------------|
| `explicit` | 用户明确「请记住…」或确认偏好 | 可达 `active` |
| `inferred` | 模型从对话推断 | 默认 `candidate`，低置信/敏感须确认 |
| `imported` | 运营导入 | 按导入策略，须审计 |

**永远不要自动 active：** 证件号、密码类、仅出现一次的订单号/验证码。

---

## 6. 验收（M0-2）

- [x] 分记忆层给出允许 / 禁止  
- [x] 字段表 ≥ 8 类（本文 14 行）  
- [x] 标明与 H6 DataPolicy 已对齐项与缺口（手机号、Cookie、URL query 等）  
- [x] 明确实现落点在 M2-4，本步不改 Runtime  

---

## 7. 不要做（本步边界）

- 不改 `AgentRuntime` / 不强制改 `DataPolicy` 代码（可列 TODO）  
- 不建 `memory_facts` 表  
- 不把本策略当成已在写库路径生效——生效以 M2-4 验收为准  
