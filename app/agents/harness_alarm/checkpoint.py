"""Alarm 可恢复检查点约定（H5-5）。

只在步骤边界存/读；payload 勿含密码明文。
"""

# checkpoint name（存进 harness_checkpoints.name）
ALARM_AFTER_FETCH = "alarm.after_fetch"
ALARM_AFTER_REPLAN = "alarm.after_replan"
ALARM_BEFORE_REPORT = "alarm.before_report"

# 各 name 的 payload 建议字段（与 runner._checkpoint_payload 对齐）
# after_fetch / after_replan / before_report 共用可恢复子集：
#   parsed, skill_meta, skill_key, skill_key_initial, config_id,
#   sources, fetch_meta, fetch_res, monitor_rate, monitor_detail,
#   error_analysis, skip_reason, fetched_pages, replans,
#   playbook_switched, idempotency_keys, message, …
#
# 幂等键格式（pipeline._step_fetch）：fetch:{config_id}:p{page}
# 键已存在则跳过 MCP/浏览器拉取。
