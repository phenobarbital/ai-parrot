"""Unit tests for the latency budget router + circuit breaker (TASK-1950).

Every test in this module must pass with the Rust extension ABSENT — that
is the normal state of the test environment until TASK-1955 lands.
"""
import pytest

from parrot.tools.compression import FilterLevel
from parrot.tools.compression.budget import (
    BudgetRouter,
    Route,
    estimate_size,
    is_rust_available,
)


@pytest.fixture
def clock():
    class Clock:
        now = 0.0

        def __call__(self):
            return self.now

        def advance(self, s):
            self.now += s

    return Clock()


@pytest.fixture
def router(clock):
    return BudgetRouter(time_fn=clock)


class TestRouting:
    def test_budget_route_decision_pre_compression(self, router):
        big = [{"a": "x" * 100} for _ in range(10_000)]
        # codec is never constructed or called to make this decision
        assert router.route(
            big, level=FilterLevel.NORMAL, codec_name="columnar",
            rust_available=False,
        ) is Route.PASSTHROUGH

    def test_minimal_always_inline(self, router):
        big = [{"a": "x" * 100} for _ in range(10_000)]
        assert router.route(
            big, level=FilterLevel.MINIMAL, codec_name="json_compact",
            rust_available=False,
        ) is Route.INLINE

    def test_no_rust_large_payload_passthrough(self, router):
        big = [{"a": "x" * 100} for _ in range(10_000)]
        assert router.route(big, level=FilterLevel.NORMAL,
                            codec_name="columnar", rust_available=False) is Route.PASSTHROUGH
        assert router.route(big, level=FilterLevel.NORMAL,
                            codec_name="columnar", rust_available=True) is Route.EXECUTOR

    def test_small_payload_inline(self, router):
        small = [{"a": 1} for _ in range(10)]
        assert router.route(small, level=FilterLevel.NORMAL,
                            codec_name="columnar", rust_available=False) is Route.INLINE

    def test_none_level_passthrough(self, router):
        small = [{"a": 1} for _ in range(10)]
        assert router.route(small, level=FilterLevel.NONE,
                            codec_name="json_compact", rust_available=False) is Route.PASSTHROUGH

    def test_defaults_match_spec(self):
        r = BudgetRouter()
        assert r.size_threshold_bytes == 256 * 1024
        assert r.row_threshold == 5000
        assert r.inline_budget_ms == 1.0
        assert r.minimal_budget_ms == 0.3
        assert r.executor_budget_ms == 15.0

    def test_thresholds_overridable(self):
        r = BudgetRouter(size_threshold_bytes=1024, row_threshold=5)
        assert r.size_threshold_bytes == 1024
        assert r.row_threshold == 5


class TestCircuitBreaker:
    def test_circuit_breaker_degrades_and_rearms(self, router, clock, caplog):
        small = [{"a": 1} for _ in range(10)]
        with caplog.at_level("WARNING"):
            for _ in range(3):  # 3 over-budget windows
                for _ in range(100):
                    router.record("columnar", duration_ms=50.0, route=Route.INLINE)
        assert router.route(small, level=FilterLevel.NORMAL,
                            codec_name="columnar", rust_available=False) is Route.PASSTHROUGH
        assert any("columnar" in r.message for r in caplog.records)

        clock.advance(301)  # cooldown elapsed
        assert router.route(small, level=FilterLevel.NORMAL,
                            codec_name="columnar", rust_available=False) is Route.INLINE
        router.record("columnar", duration_ms=0.2, route=Route.INLINE)
        assert router.route(small, level=FilterLevel.NORMAL,
                            codec_name="columnar", rust_available=False) is Route.INLINE

    def test_breaker_is_per_codec(self, router):
        for _ in range(3):
            for _ in range(100):
                router.record("columnar", duration_ms=50.0, route=Route.INLINE)
        small = [{"a": 1} for _ in range(10)]
        assert router.route(small, level=FilterLevel.MINIMAL,
                            codec_name="json_compact", rust_available=False) is Route.INLINE

    def test_failed_probe_reopens_and_restarts_cooldown(self, router, clock):
        for _ in range(3):
            for _ in range(100):
                router.record("columnar", duration_ms=50.0, route=Route.INLINE)
        clock.advance(301)
        small = [{"a": 1} for _ in range(10)]
        # probe allowed through
        assert router.route(small, level=FilterLevel.NORMAL,
                            codec_name="columnar", rust_available=False) is Route.INLINE
        # probe itself busts budget -> breaker reopens
        router.record("columnar", duration_ms=50.0, route=Route.INLINE)
        assert router.route(small, level=FilterLevel.NORMAL,
                            codec_name="columnar", rust_available=False) is Route.PASSTHROUGH
        # cooldown restarted: not yet elapsed
        clock.advance(1)
        assert router.route(small, level=FilterLevel.NORMAL,
                            codec_name="columnar", rust_available=False) is Route.PASSTHROUGH

    def test_empty_window_does_not_advance_consecutive_count(self, router, clock):
        # A window that times out with zero further calls must not count
        # toward the 3-consecutive-over-budget-windows threshold.
        router.record("columnar", duration_ms=0.1, route=Route.INLINE)  # prime state
        small = [{"a": 1} for _ in range(10)]
        for _ in range(5):  # each iteration: one window expires empty
            clock.advance(61)  # window_seconds default is 60
            assert router.route(small, level=FilterLevel.NORMAL,
                                codec_name="columnar", rust_available=False) is Route.INLINE

    def test_p99_exposed_for_report(self, router):
        for ms in [1.0, 2.0, 3.0, 100.0]:
            router.record("columnar", duration_ms=ms, route=Route.INLINE)
        p99 = router.p99("columnar")
        assert p99 is not None
        assert p99 >= 3.0

    def test_p99_none_when_no_calls(self, router):
        assert router.p99("never_called") is None


class TestEstimateSize:
    def test_empty_list(self):
        assert estimate_size([]) == (0, 0)

    def test_list_of_dicts(self):
        n_bytes, n_rows = estimate_size([{"a": 1}] * 100)
        assert n_rows == 100
        assert n_bytes > 0

    def test_non_list_has_zero_rows(self):
        _, n_rows = estimate_size({"a": 1})
        assert n_rows == 0

    def test_never_fully_serializes_large_payload(self):
        # A huge homogeneous list must be estimated in ~O(1) sample time,
        # not by walking every element.
        big = [{"a": "x" * 1000}] * 1_000_000
        n_bytes, n_rows = estimate_size(big)
        assert n_rows == 1_000_000
        assert n_bytes > 0


def test_is_rust_available_absent_in_test_env():
    # The parrot_codec extension does not exist yet (TASK-1955).
    assert is_rust_available() is False
