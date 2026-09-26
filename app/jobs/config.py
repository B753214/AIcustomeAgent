"""记忆保留天数（对齐 plan/memory_retention_policy.md）。"""

# active：最后活动后 idle 天数（本步暂不自动归档，仅预留）
retention_active_idle_days = 180
# ended / archived：ended_at 后再留
retention_ended_days = 30
# soft-delete：updated_at 后再硬删
retention_soft_delete_days = 7
# harness_runs：ended_at 后
retention_run_days = 90
# harness_checkpoints：所属 Run 终态 ended_at 后
retention_checkpoint_days = 7
