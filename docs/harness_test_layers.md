# Harness 测试分层地图（H7-1）

离线优先：不依赖真实 LLM / PostgreSQL / Milvus / MCP / 浏览器。  
CI：`.github/workflows/offline-tests.yml` → `pytest tests/ -q`。

## 分层对照

| 层 | 测什么 | 主要文件 |
|---|---|---|
| **Contract** | 契约形状、`EVENT_TYPES`、`HarnessError` | `tests/test_harness_contracts.py` |
| **Unit** | Runtime / Policy / Router / Registry / ToolRunner / Adapter / Storage | `test_agent_runtime.py`、`test_harness_policies.py`、`test_policy_registry.py`、`test_router.py`、`test_*_registry.py`、`test_tool_runner.py`、`test_model_gateway.py`、`test_*_harness_adapter.py`、`test_harness_*_repository.py`、`test_harness_persist.py`、`test_harness_redact_runtime.py` |
| **Golden** | 固定输入 → 规则层期望（不调真模型） | `tests/golden/*.json`、`tests/test_golden_scenarios.py` |
| **Replay** | 标准事件序列可序列化回放（不花真钱） | `tests/test_harness_replay.py`、`test_harness_run_http.py`（按 run_id 组装） |
| **Failure** | 取消、策略拒绝、超时、工具失败 | `test_cancellation.py`、`test_policy_registry.py`（strict/budget）、`test_harness_failure_injection.py`、`test_tool_runner.py`（超时/`[TOOL_ERROR]`） |

## 领域 / 其它离线测

| 类别 | 文件 |
|---|---|
| Alarm 规则 / Pipeline | `test_alarm*.py`、`test_alarm_checkpoint_resume.py` |
| Chat ReAct / 工具校验 | `test_chat_react.py`、`test_tool_validation.py` |
| RAG / PDF | `test_rag_retrieval.py`、`test_pdf_*.py` |
| 横切 | `test_auth.py`、`test_ratelimit.py`、`test_resilience.py`、`test_semantic_cache.py`、`test_tracing.py` |
| Eval 脚本单元（mock） | `test_agent_eval.py`、`test_knowledge_eval.py` |

## Failure 注入约定（H7-1）

| 场景 | 期望 |
|---|---|
| Executor / 模型侧超时 | `run.failed`，`payload.category == "timeout"` |
| 工具失败（`[TOOL_ERROR]` / raise） | ToolRunner → `HarnessError(TOOL)`；经 Runtime 则 `run.failed` + `category == "tool"` |
| 取消 | `run.failed` + `cancelled: true`（见 `test_cancellation.py`） |
| 策略拒绝 | `run.failed` + `category == "policy"` |

## 本地命令

```powershell
# 全量离线（与 CI 一致）
pytest tests/ -q --tb=short

# 分层抽查
pytest tests/test_harness_contracts.py tests/test_harness_failure_injection.py tests/test_harness_replay.py tests/test_golden_scenarios.py -q
```

在线 Eval（真模型 / 真库）见 `eval/README.md`，属 **H7-2**，不挡 H7-1。
