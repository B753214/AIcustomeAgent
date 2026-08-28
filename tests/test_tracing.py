"""P5-4 链路追踪环形缓冲单元测试。"""
from app.services.tracing import TraceRecorder


def test_recent_and_summary():
    recorder = TraceRecorder(max_entries=5)
    recorder.record({"total_ms": 100, "cache_hit": True, "cache_checked": True, "intent": "knowledge"})
    recorder.record({"total_ms": 200, "cache_hit": False, "cache_checked": True, "intent": "chat"})
    recorder.record({"total_ms": 300, "cache_hit": False, "cache_checked": False, "intent": "order"})
    recorder.record({"total_ms": 400, "status": 200})

    assert len(recorder.recent()) == 4
    summary = recorder.summary()
    assert summary["total"] == 4
    assert summary["p95_ms"] == 400
    assert summary["avg_ms"] == 250.0
    assert summary["cache_hit_rate"] == 0.5
    assert summary["by_intent"]["knowledge"] == 1


def test_ring_capacity_drops_oldest():
    recorder = TraceRecorder(max_entries=2)
    recorder.record({"total_ms": 1})
    recorder.record({"total_ms": 2})
    recorder.record({"total_ms": 3})
    assert [e["total_ms"] for e in recorder.recent()] == [3, 2]


def test_empty_summary():
    assert TraceRecorder().summary()["total"] == 0


def test_blocked_count_in_summary():
    recorder = TraceRecorder(max_entries=10)
    recorder.record({"total_ms": 0, "status": 429, "intent": "ratelimited"})
    recorder.record({"total_ms": 100, "status": 200, "intent": "chat"})
    assert recorder.summary()["blocked"] == 1
