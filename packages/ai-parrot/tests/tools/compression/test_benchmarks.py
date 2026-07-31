"""Latency benchmark suite + threshold calibration for the compression
pipeline (TASK-1959, spec G7/G9).

Not part of the normal unit-test path: every test here is gated behind
`PARROT_RUN_BENCHMARKS=1` (self-contained — no changes to any conftest.py
required, unlike `tests/benchmarks/`'s `--benchmark-only` convention, which
only applies once that directory is part of the collected tree). Also
carries `@pytest.mark.benchmark` for consistency with that repo-wide
convention when the full suite IS collected.

Run explicitly with:
    PARROT_RUN_BENCHMARKS=1 pytest packages/ai-parrot/tests/tools/compression/test_benchmarks.py -v -s

Calibrated on: Intel Core i7-9850H @ 2.60GHz, 12 logical cores,
Python 3.11.15, Linux, no Rust extension compiled (pure-Python path).
Tolerances here are deliberately generous (2x the budget) so a loaded
shared machine does not produce noise failures — see spec G7 framing.
"""
import asyncio
import os
import statistics
import time

import pytest

import parrot.tools.compression.codecs  # noqa: F401 — registers built-in codecs
from parrot.tools.compression import FilterLevel, get_codec
from parrot.tools.compression.budget import BudgetRouter, Route

pytestmark = [
    pytest.mark.benchmark,
    pytest.mark.skipif(
        not os.environ.get("PARROT_RUN_BENCHMARKS"),
        reason=(
            "Latency benchmarks are opt-in — set PARROT_RUN_BENCHMARKS=1 "
            "to run them. Excluded from the default unit-test path (they "
            "measure wall-clock time and are sensitive to machine load)."
        ),
    ),
]

# Tolerance multiplier applied to every budget assertion (spec: "a
# documented multiplier ... so a loaded machine does not produce noise
# failures").
TOLERANCE = 2.0

# Read from BudgetRouter's actual (calibrated, TASK-1959) defaults rather
# than hardcoding a second copy here — keeps this suite from silently
# drifting out of sync with budget.py if the defaults are recalibrated again.
_default_router = BudgetRouter()
MINIMAL_BUDGET_MS = _default_router.minimal_budget_ms
INLINE_BUDGET_MS = _default_router.inline_budget_ms

# G9 loop-lag bound: near-zero is expected (PASSTHROUGH does no work on the
# loop at all); this bound only needs to be far below what an ACTUAL
# synchronous compression of a 20k-row payload would cost (which would be
# tens to hundreds of milliseconds), not tight against scheduler noise.
MAX_LOOP_LAG_MS = 50.0


# -- pure-Python payload generators (no pandas/numpy) -----------------------

def _rows(n: int, *, wide: bool = False, str_size: int = 8) -> list[dict]:
    width = 20 if wide else 7
    return [
        {
            "store_id": f"S{i:05d}", "revenue": 1000.0 + i, "region": "south",
            "active": True, "notes": None,
            **{f"c{j}": ("x" * str_size + str((i * j) % 7)) for j in range(width)},
        }
        for i in range(n)
    ]


def _nested_rows(n: int) -> list[dict]:
    return [{"a": {"nested": i}, "b": [1, 2, 3], "c": None} for i in range(n)]


def _heterogeneous_rows(n: int) -> list[dict]:
    return [{f"k{i}": i, "shared": 1} for i in range(n)]


PAYLOAD_CLASSES = {
    "small_10": _rows(10),
    "typical_500x12": _rows(500),
    "large_5000x12": _rows(5_000),
    "huge_over_threshold": _rows(5_000, wide=True, str_size=64),  # > 256 KB
    "heterogeneous_30": _heterogeneous_rows(30),
    "deeply_nested_30": _nested_rows(30),
}


def _p50(samples: list[float]) -> float:
    return statistics.median(samples)


def _p99(samples: list[float]) -> float:
    s = sorted(samples)
    return s[min(len(s) - 1, int(len(s) * 0.99))]


def _measure(codec, payload, level, n=300, warmup=20):
    for _ in range(warmup):
        codec.compress(payload, level=level, params={})
    times: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        codec.compress(payload, level=level, params={})
        times.append((time.perf_counter() - t0) * 1000)
    return _p50(times), _p99(times)


async def _loop_lag_during(coro, interval: float = 0.005) -> float:
    """Run `coro` while a heartbeat task samples event-loop scheduling
    delay; returns the max observed lag in milliseconds. A blocked loop
    shows up as `asyncio.sleep(interval)` taking far longer than
    `interval`."""
    lags: list[float] = []

    async def heartbeat():
        while True:
            t0 = time.perf_counter()
            await asyncio.sleep(interval)
            lags.append((time.perf_counter() - t0 - interval) * 1000)

    hb = asyncio.create_task(heartbeat())
    try:
        await coro
    finally:
        hb.cancel()
        try:
            await hb
        except asyncio.CancelledError:
            pass
    return max(lags) if lags else 0.0


class TestLatencyBudgets:
    """G7: inline path <= 1 ms p99 (<= 0.3 ms for MINIMAL)."""

    def test_minimal_inline_p99_under_budget(self):
        codec = get_codec("json_compact")()
        payload = PAYLOAD_CLASSES["typical_500x12"]
        p50, p99 = _measure(codec, payload, FilterLevel.MINIMAL)
        print(f"\njson_compact MINIMAL (typical 500x12): p50={p50:.4f}ms p99={p99:.4f}ms")
        assert p99 <= MINIMAL_BUDGET_MS * TOLERANCE, (
            f"json_compact MINIMAL p99={p99:.4f}ms exceeds budget "
            f"{MINIMAL_BUDGET_MS}ms x{TOLERANCE} tolerance"
        )

    def test_normal_inline_p99_under_budget(self):
        codec = get_codec("columnar")()
        payload = PAYLOAD_CLASSES["typical_500x12"]
        p50, p99 = _measure(codec, payload, FilterLevel.NORMAL)
        print(f"\ncolumnar NORMAL (typical 500x12): p50={p50:.4f}ms p99={p99:.4f}ms")
        assert p99 <= INLINE_BUDGET_MS * TOLERANCE, (
            f"columnar NORMAL p99={p99:.4f}ms exceeds budget "
            f"{INLINE_BUDGET_MS}ms x{TOLERANCE} tolerance"
        )

    def test_all_payload_classes_reported(self, capsys):
        """Full p50/p99 table across every payload class, for both codecs
        where applicable — printed for the Completion Note record, not
        gated on a hard assertion (heterogeneous/nested/huge payloads are
        NOT expected to fit the inline budget by design)."""
        json_codec = get_codec("json_compact")()
        columnar_codec = get_codec("columnar")()
        print("\n--- Latency benchmark table (ms) ---")
        for name, payload in PAYLOAD_CLASSES.items():
            n = 300 if len(payload) <= 500 else 50
            jp50, jp99 = _measure(json_codec, payload, FilterLevel.MINIMAL, n=n)
            cp50, cp99 = _measure(columnar_codec, payload, FilterLevel.NORMAL, n=n)
            print(
                f"{name:<24} rows={len(payload):<6} "
                f"json_compact(p50={jp50:.4f},p99={jp99:.4f}) "
                f"columnar(p50={cp50:.4f},p99={cp99:.4f})"
            )
        captured = capsys.readouterr()
        assert "Latency benchmark table" in captured.out

    def test_crossover_point_is_reported(self, capsys):
        """Find and print the row count where columnar's p99 exceeds the
        1 ms inline budget (informational — the crossover is expected to
        sit well above typical payload sizes; this does not gate a pass/
        fail, it feeds the Completion Note's calibration record)."""
        codec = get_codec("columnar")()
        crossover_rows = None
        for n_rows in (100, 500, 1_000, 2_000, 5_000, 10_000, 20_000):
            payload = _rows(n_rows)
            _, p99 = _measure(codec, payload, FilterLevel.NORMAL, n=30, warmup=5)
            print(f"columnar NORMAL @ {n_rows} rows: p99={p99:.4f}ms")
            if crossover_rows is None and p99 > INLINE_BUDGET_MS:
                crossover_rows = n_rows
        print(
            f"Crossover point (p99 > {INLINE_BUDGET_MS}ms): "
            f"{crossover_rows if crossover_rows else 'not reached up to 20,000 rows'}"
        )
        captured = capsys.readouterr()
        assert "Crossover point" in captured.out


class TestNoLoopBlocking:
    """G9: no synchronous compression above the threshold ever runs on the
    event loop. Without the Rust extension, an over-threshold payload MUST
    route to PASSTHROUGH — never EXECUTOR (which, without GIL release, is
    theater) and never a blocking INLINE compress()."""

    async def test_over_threshold_routes_to_passthrough_without_rust(self):
        router = BudgetRouter()
        huge = PAYLOAD_CLASSES["huge_over_threshold"]
        route = router.route(
            huge, level=FilterLevel.NORMAL, codec_name="columnar", rust_available=False,
        )
        assert route is Route.PASSTHROUGH

    async def test_over_threshold_never_blocks_loop(self):
        """Directly exercises `CompressionStage.run()` (not just the
        router's route() decision) on a huge payload with no tee/rust, and
        confirms the event loop stayed responsive throughout — the
        mechanical proof of G9."""
        from parrot.tools.compression import CompressorRegistry
        from parrot.tools.compression.config import CompressorEntry
        from parrot.tools.compression.stage import CompressionStage

        registry = CompressorRegistry(
            {"*": CompressorEntry(codec="columnar", level=FilterLevel.NORMAL)}
        )
        # A dummy (always-"available") tee so NORMAL isn't capped to MINIMAL
        # by the G3 guard (TASK-1953) — MINIMAL always routes INLINE
        # regardless of size, which would defeat this G9 test's purpose.
        stage = CompressionStage(
            registry=registry, router=BudgetRouter(), rust_available=False,
            tee=lambda tool_name, payload, codec_name: None,
        )
        huge = PAYLOAD_CLASSES["huge_over_threshold"]

        async def run_stage():
            return await stage.run(
                "huge_tool", huge, status="success", metadata={}, return_direct=False,
            )

        lag = await _loop_lag_during(run_stage())
        print(f"\nMax event-loop lag during over-threshold compression: {lag:.2f}ms")
        assert lag < MAX_LOOP_LAG_MS, f"event loop blocked {lag:.1f}ms (bound {MAX_LOOP_LAG_MS}ms)"

        # Confirm it actually took the PASSTHROUGH route (not a silent
        # inline compression that merely happened to be fast enough).
        out, meta = await run_stage()
        assert meta.get("compression_skipped") == "budget_passthrough"
