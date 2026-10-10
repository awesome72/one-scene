import pytest

from app.engine import metering


def test_cost_prices_cache_tiers() -> None:
    base = {"model": "claude-sonnet-5-5", "input": 1_000_000, "output": 0}
    assert metering.cost(base) == pytest.approx(2.0)
    # 5분 캐시 쓰기 1.25배, 1시간 캐시 쓰기 2배, 캐시 읽기 0.1배
    assert metering.cost({**base, "input": 0, "cache_write": 1_000_000}) == pytest.approx(2.5)
    assert metering.cost({**base, "input": 0, "cache_write": 1_000_000,
                          "cache_write_1h": 1_000_000}) == pytest.approx(4.0)
    assert metering.cost({**base, "input": 0, "cache_read": 1_000_000}) == pytest.approx(0.2)
    assert metering.cost({"model": "unknown", "input": 5, "output": 5}) == 0.0


def test_record_without_sink_is_noop() -> None:
    metering.record({"model": "x", "input": 1, "output": 1})  # 요청 밖 호출(평가 등)은 버린다
