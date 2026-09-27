# 长期事实分类策略（Memory-M4-1）

> 对应完善计划 M4-1：定义可记忆 / 不可记忆。  
> 表模型：`app/models/memory_facts.py`（`memory_facts`）。  
> 规则代码：`app/services/memory/fact_policy.py`（本步只做分类判定，不抽 LLM、不写库）。

---

## 1. `kind` 取值

| kind | 含义 | 示例 |
|------|------|------|
| `profile` | 相对稳定的身份/称呼 | 姓名、称呼偏好 |
| `preference` | 交互或产品偏好 | 回复要简洁、语言中文 |
| `constraint` | 硬约束 | 不要电话联系、过敏原 |
| `business_fact` | 跨会话仍成立的业务事实 | 常用项目代号、固定告警 config 偏好 |

---

## 2. 可记忆 vs 不可记忆

| 类别 | 是否可进 `memory_facts` | 默认 status | 说明 |
|------|:----------------------:|:-----------:|------|
| 用户显式「请记住…」的偏好/约束 | ✅ | 可达 `active`（非敏感） | `source_type=explicit` |
| 用户明确自报稳定身份信息（姓名等） | ✅ | `active` 或 `candidate` | 敏感字段仍禁或须确认 |
| 模型从对话**推断**的偏好 | ⚠️ 仅候选 | **必须** `candidate` | 须确认后才能 `active` |
| 天气、气温、今日预报 | ❌ | — | 只留 Short-term / Summary 表述 |
| 单次物流/订单状态、验证码、临时单号 | ❌ | — | 瞬时业务，不进长期 |
| 未确认的「用户可能喜欢…」猜测 | ❌ 或仅 `candidate` | `candidate` | **禁止**自动 `active` |
| 密码、Token、Cookie、证件号、手机号 | ❌ | — | 对齐 `memory_data_policy`；Semantic 禁 |
| 单次告警排查中间态 | ❌ | — | 用 Episodic，不进 Semantic |

---

## 3. 写入门槛（与 status）

| source_type | 可写库？ | 初始 status |
|-------------|:--------:|-------------|
| `explicit` | 是（且通过「可记忆」表） | 非敏感 → 可 `active`；敏感 → `candidate` 或拒绝 |
| `inferred` | 仅当通过过滤 | **一律** `candidate`（低置信/敏感须确认） |
| `imported` | 运营导入 | 按导入策略，须审计（M4-7） |

**硬规则**

1. 低置信（建议 `confidence < 0.7`）→ 不能 `active`，最多 `candidate`。  
2. 天气 / 临时订单 / 纯猜测 → **不写入**（函数返回 reject）。  
3. 永远不要自动 `active`：证件号、密码类、一次性验证码/订单号。

---

## 3.1 自动写入 vs 待确认（M4-5）

| 配置 | 含义 |
|------|------|
| `memory_fact_extract_enabled` | 总开关；默认 `False` |
| `memory_fact_trigger_mode` | `off` / `heuristic`（默认）/ `always` |
| `memory_fact_auto_active` | `False` 时即使 explicit 高置信也先 `candidate` |
| `memory_fact_min_confidence_active` | 升 `active` 的最低置信（默认 0.7） |

**触发（heuristic）**：用户句命中「请记住 / 我叫 / 以后请…」等再抽；闲聊不抽。  
**挂点**：`chat._persist_chat_turn` → `maybe_persist_facts_from_turn`；失败只打 warning，不阻断主对话。  
**确认/CRUD API**：M4-6。

---

## 4. 验收（M4-1）

- [x] 有可记 / 不可记对照表（含天气、临时订单、模型猜测）  
- [x] `kind` / `source_type` / `status` 门槛写清  
- [x] 纯函数 `should_persist_fact` 可单测（不落库、不调 LLM）  
- [x] 跟做计划勾选 M4-1  

**本步不做：** LLM 抽取（M4-2）、去重 supersede（M4-3/4）、CRUD API（M4-6）。
