# 黄金场景快照（Harness H0-6）

供 H1～H4 改造时对照回归，**冻结当前产品路径的标准输入与期望**。

| 文件 | Agent | 最少条数 |
|---|---|---|
| `chat.json` | 闲聊 / 工具 | ≥2 |
| `knowledge.json` | RAG 知识问答 | ≥2 |
| `alarm.json` | 告警 detect/parse/classify（规则层可离线验） | ≥2 |
| `manifest.json` | 索引与元数据 | — |

## 字段约定

每条 case：

```json
{
  "id": "chat-order-001",
  "agent": "chat|knowledge|alarm",
  "title": "短标题",
  "input": "用户原话",
  "route": {
    "intent": "chat|knowledge|alarm|order",
    "notes": "可选说明"
  },
  "expected": {
    "tools": ["query_order"],
    "required_all": ["已发货"],
    "required_any": [],
    "forbidden": ["编造"],
    "events": ["run.started", "tool.started", "run.completed"],
    "offline": { "...规则层可断言字段..." }
  },
  "source": "来源说明"
}
```

- `expected.events`：面向未来 Runtime 标准事件（H1+），当前不必全部产生。  
- `expected.offline`：可在**不调 LLM** 时用现有函数断言（H0-6 测试会跑这部分）。  
- 在线全链路（真模型）对照放到后续 Eval / H7，不在本目录强制执行。

## 本地校验

```powershell
pytest tests/test_golden_scenarios.py -q
```
