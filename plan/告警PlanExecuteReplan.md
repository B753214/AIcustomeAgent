# 告警 Agent：约束型 Plan → Execute → Replan

跟做方式：**分日交付**；对话说 **「开始 Alarm-PER-DayN」**。

目标：首轮仍走**预设步骤**；执行后根据证据决定两件事：

1. **要不要补第二页明细**
2. **要不要换 playbook 再出报告**

不是让模型从零编计划。

---

## 一、结论摘要

| 项 | 决策 |
|----|------|
| 模式 | **约束型 P&E + Replan**（步骤只能从目录选） |
| 首轮计划 | **规则生成**，不调 LLM：parse →（可选 classify）→ fetch p1 →（可选 skip）→ report |
| Replan | **规则优先**；拿不准时才用小 LLM 在 `{fetch_page2, switch_playbook, finish}` 里勾选 |
| 上限 | 补页 **最多 1 次**；换 playbook **最多 1 次**；总循环 ≤ 3 |
| 拉数链 | 仍 **MCP → 浏览器 → 正文**；分页目前浏览器有 `page`；MCP 无 page 则补页走浏览器 |
| 明确不做 | 自由规划；无限翻页；把 knowledge/chat 改成 P&E |

---

## 二、预设步骤目录（只能从这里选）

| id | 作用 | 何时可 skip |
|----|------|-------------|
| `parse` | 解析告警/URL | 不可 skip |
| `classify` | 按指标名推断类型 | 已有【类型】/【报警类型】/【分类】 |
| `fetch` | 拉 rate + detail（指定 page） | 无 `marketConfigId` |
| `analyze_detail` | `analyze_error_details` | 无明细 |
| `skip_report` | count=0 直接短报告 | count≠0 |
| `report` | playbook + LLM 出报告 | 已 skip_report |

**禁止**发明 `search_web`、`ask_user` 等目录外步骤。

---

## 三、目标循环

```text
plan_0（规则）
  parse → [classify?] → fetch(page=1) → analyze_detail → skip_report | report

execute
  得到：rate、detail（≤50）、error_analysis、skill_key、draft_report?

replan（规则，必要时 LLM）
  A. 明细打满一页 且 证据偏弱 → fetch(page=2)，合并 list，再 analyze
  B. 明细指向的类型 ≠ 当前 playbook → 换 key，reload playbook，再 report
  C. 否则 finish

execute 增量步骤 → 再 replan 直到 finish 或 达上限
```

```text
页1 50 条且像截断 ──► 补第 2 页 ──► 合并后再分析
明细像 BFF、playbook 是 render ──► 换成 bff playbook ──► 再出报告
```

---

## 四、Replan 触发（先写死，再可选 LLM）

### 4.1 补第二页 `fetch_page2`

同时满足才建议补页：

- 本页 `list` 条数 **≥ pageSize（50）**（打满，可能还有）
- 当前 `page == 1` 且尚未补过页
- 通道支持分页（**浏览器**；MCP 本轮无 page 则补页改走浏览器）
- 证据偏弱（满足其一即可）：
  - Top1 错误占比 &lt; 40%（类型分散，一页代表性差）
  - `uniqueUsers` 很少但 `count` 很大（抽样偏差）
  - 报告结论过短 / 证据不足 3 条（若已出过草稿）

不补页：`count==0`、正文降级、已 page=2、条数 &lt; 50。

### 4.2 换 playbook `switch_playbook`

- 用**明细**再跑一遍 `classify_by_name`（拼 top err_msg + page_name + url）
- 得到 `hint_key`，与当前 `skill_key` **不同**
- 且 `hint_key` 不是胡乱 precise（例如明细里明确有 bff/ajx/白屏等）
- 本轮尚未换过 playbook
- **用户显式【类型】优先**：有 `alarmType` 且已解析成功 → **不换**（尊重输入）

换完：`load_playbook(new_key)`，用**已拉数据**再调一次 LLM，不重拉（除非同时需要补页：先补页再换本）。

### 4.3 顺序

同一轮若两条件都中：

1. 先 `fetch_page2`（证据变了可能改分类）
2. 再判断 `switch_playbook`
3. 最后 `report`（若还没出或 playbook 变了）

---

## 五、计划表（按日）

| Day | 主题 | 交付物 | 过关标准 |
|-----|------|--------|----------|
| **Day1** | 分页拉数 | `fetch` 支持 `page`；浏览器 `page` 透传；合并 list | page=2 能拉到另一批或空；MCP 无分页则标记 `pagination=browser_only` |
| **Day2** | Replan 规则 | `replan.py`：`should_fetch_page2` / `should_switch_playbook` | 单测：50 条分散→补页；白屏指标+BFF 明细→换 bff；有 alarmType→不换 |
| **Day3** | 执行器 | `pipeline.py`：目录步骤 + 状态（page, skill, details, report） | 首轮仍等价现 runner（无 Replan 时行为不变） |
| **Day4** | 接入 runner | `run_alarm_agent` / stream 走循环；SSE 打出「补第2页」「更换 playbook」 | 流式不 500；meta 含 `replans` |
| **Day5** | 上限 / 开关 / 观测 | `ALARM_REPLAN_ENABLED`、`MAX_PAGES=2`、`MAX_PLAYBOOK_SWITCH=1` | 关闭=旧流水线；打开最多 1 次补页+1 次换本 |
| **Day6** | LLM Replan | 补页与换本冲突时 LLM 三选一 | 非法输出回退先补页；无单独开关 |
| **Day7** | 收尾 | README、单测 | 计划打勾 |

建议：**Day1–5 必做**；Day6 仅当规则误触发多再加。

---

## 六、状态与返回

```python
state = {
  "page": 1,
  "skill_key": "render",
  "fetched_pages": [1],
  "playbook_switched": False,
  "monitor_rate": {},
  "monitor_detail": {"list": []},  # 合并后
  "error_analysis": {},
  "reply": None,
  "replans": [],  # ["fetch_page2", "switch_playbook:bff"]
}
```

`meta` 增加：`page_count`、`skill_key`、`skill_key_initial`、`replans`。

---

## 七、配置

| 变量 | 默认 | 含义 |
|------|------|------|
| `ALARM_REPLAN_ENABLED` | `false` 先灰度 / 或 `true` | 总开关 |
| `ALARM_DETAIL_PAGE_SIZE` | `50` | 与现网一致 |
| `ALARM_REPLAN_MAX_PAGES` | `2` | 含第一页 |
| `ALARM_REPLAN_MAX_PLAYBOOK_SWITCH` | `1` | |
| （Day6）LLM 仲裁 | 冲突时默认开启 | 补页与换本同时成立时三选一；无 env 开关 |

---

## 八、风险

1. **MCP 无 page**：补页必须浏览器；无登录则放弃补页并在 meta 标明。
2. **延迟**：最坏 +1 次浏览器拉数 +1 次 LLM 报告；用上限和开关兜住。
3. **换 playbook 抖动**：显式类型锁定；hint 必须关键词够强。
4. **合并明细超长**：喂 LLM 仍截断 3000 字；分析可用合并后的 list（可再 cap 100 条）。

---

## 九、验收样例

| 场景 | 期望 |
|------|------|
| 普通告警，明细 8 条 | 不补页、不换本，与现在一致 |
| 浏览器 50 条且 Top1 &lt; 40% | `replans` 含 `fetch_page2` |
| 【指标】白屏，明细全是 BFF/接口失败 | 无【类型】时换 `bff` 再报告 |
| 【类型】：渲染异常，明细像 BFF | **不换** playbook |
| `ALARM_REPLAN_ENABLED=false` | 无任何 replan |
| count=0 | 仍 skip LLM，不补页 |

---

## 十、打勾进度

- [x] Alarm-PER-Day1 分页拉数
- [x] Alarm-PER-Day2 Replan 规则
- [x] Alarm-PER-Day3 执行器
- [x] Alarm-PER-Day4 接入 runner / SSE
- [x] Alarm-PER-Day5 开关与上限
- [x] Alarm-PER-Day6 LLM Replan
- [x] Alarm-PER-Day7 收尾

---

## 十一、完成说明

Alarm-PER 已全部交付：约束型 Plan → Execute → Replan（规则 + 冲突时 LLM 仲裁）。总开关 `ALARM_REPLAN_ENABLED` 默认关；打开后最多补 1 页、换本 1 次。
