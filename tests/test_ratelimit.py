"""P5-2 滑动窗口限流单元测试。"""
import time

from app.services.ratelimit import SlidingWindowLimiter


def test_sliding_window_blocks_over_limit():
    limiter = SlidingWindowLimiter(limit_per_minute=5, window_sec=60)
    assert all(limiter.allow("ip-1") for _ in range(5))
    assert not limiter.allow("ip-1")
    assert limiter.allow("ip-2")
    assert limiter.stats()["blocked"] == 1


def test_window_expiry_allows_again():
    limiter = SlidingWindowLimiter(limit_per_minute=2, window_sec=0.2)
    assert limiter.allow("ip-x")
    assert limiter.allow("ip-x")
    assert not limiter.allow("ip-x")
    time.sleep(0.3)
    assert limiter.allow("ip-x")


def test_stats_reflects_config():
    limiter = SlidingWindowLimiter(limit_per_minute=10, window_sec=30)
    limiter.allow("a")
    limiter.allow("b")
    stats = limiter.stats()
    assert stats["limit_per_minute"] == 10
    assert stats["window_sec"] == 30
    assert stats["active_keys"] == 2
    assert stats["blocked"] == 0
