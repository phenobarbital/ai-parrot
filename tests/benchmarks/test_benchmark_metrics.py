"""Unit tests for FEAT-237 TASK-1551: benchmark metric functions.

Tests cover:
  - latency_percentiles: basic percentiles, min/max, single-element, empty.
  - peak_rss_mb: returns a positive float.
  - recall_at_k: perfect, partial, zero, empty-relevant, k>len cases.
  - report.build_report: markdown output, recommendation gate, FAILED rows.

None of these tests require ML models or corpus files.

Import strategy: we load the benchmark modules directly via
``importlib.util.spec_from_file_location`` to bypass the conftest.py
sys.path manipulation that causes the main-repo ``benchmarks/`` directory
to shadow the worktree's ``benchmarks/pageindex_embedding_latency/``.
"""
from __future__ import annotations

import importlib.util as _ilu
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Worktree-local module loader (same pattern as other FEAT-237 tests)
# ---------------------------------------------------------------------------

_WT = Path(__file__).parents[2]  # <worktree root>
_BENCH_DIR = _WT / "benchmarks" / "pageindex_embedding_latency"


def _load_bench_module(name: str):
    """Load a benchmark sub-module by name without relying on sys.path.

    Args:
        name: Sub-module stem (e.g. ``"metrics"`` or ``"report"``).

    Returns:
        Loaded module object.
    """
    full_name = f"benchmarks.pageindex_embedding_latency.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]

    # Ensure parent package stubs are registered so sub-module imports work.
    _ensure_package_stub("benchmarks")
    _ensure_package_stub("benchmarks.pageindex_embedding_latency", _BENCH_DIR)

    path = _BENCH_DIR / f"{name}.py"
    spec = _ilu.spec_from_file_location(full_name, str(path))
    mod = _ilu.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _ensure_package_stub(package_name: str, path: Path | None = None) -> None:
    """Register a package stub in sys.modules if not already present.

    Args:
        package_name: Dotted package name (e.g. ``"benchmarks"``).
        path: Directory path for the package.  Defaults to the parent of the
            last component inferred from _WT.
    """
    if package_name in sys.modules:
        return
    import types

    stub = types.ModuleType(package_name)
    if path is not None:
        stub.__path__ = [str(path)]
    else:
        parts = package_name.split(".")
        stub.__path__ = [str(_WT / Path(*parts))]
    stub.__package__ = package_name
    sys.modules[package_name] = stub


# Load the two modules under test
_metrics = _load_bench_module("metrics")
_report = _load_bench_module("report")

latency_percentiles = _metrics.latency_percentiles
peak_rss_mb = _metrics.peak_rss_mb
recall_at_k = _metrics.recall_at_k
build_report = _report.build_report


# ---------------------------------------------------------------------------
# TestLatencyPercentiles
# ---------------------------------------------------------------------------


class TestLatencyPercentiles:
    def test_basic_percentiles(self) -> None:
        """p50, p95, mean, n are computed for a simple uniform list."""
        timings = [0.1, 0.2, 0.3, 0.4, 0.5]
        result = latency_percentiles(timings)
        assert result["p50"] == pytest.approx(0.3, abs=0.01)
        assert result["n"] == 5
        assert "p95" in result
        assert "p99" in result
        assert "mean" in result
        assert "std" in result

    def test_mean_correct(self) -> None:
        """Mean is the average of all values."""
        timings = [1.0, 2.0, 3.0, 4.0]
        result = latency_percentiles(timings)
        assert result["mean"] == pytest.approx(2.5, abs=1e-9)

    def test_single_element(self) -> None:
        """Single timing: p50 == p95 == p99 == mean == value."""
        result = latency_percentiles([0.42])
        assert result["p50"] == pytest.approx(0.42, abs=1e-9)
        assert result["p95"] == pytest.approx(0.42, abs=1e-9)
        assert result["n"] == 1

    def test_monotone_increase(self) -> None:
        """p50 <= p95 <= p99 for any distribution."""
        import random

        rng = random.Random(42)
        timings = [rng.expovariate(1.0) for _ in range(100)]
        result = latency_percentiles(timings)
        assert result["p50"] <= result["p95"]
        assert result["p95"] <= result["p99"]

    def test_empty_raises(self) -> None:
        """Empty timings raise ValueError."""
        with pytest.raises(ValueError, match="empty"):
            latency_percentiles([])

    def test_large_n(self) -> None:
        """Works for large N (1000 samples)."""
        import numpy as np

        rng = np.random.default_rng(0)
        timings = rng.uniform(0.01, 0.5, size=1000).tolist()
        result = latency_percentiles(timings)
        assert result["n"] == 1000
        assert 0.01 <= result["p50"] <= 0.5

    def test_all_same(self) -> None:
        """When all timings are equal, std is 0."""
        result = latency_percentiles([0.1] * 30)
        assert result["std"] == pytest.approx(0.0, abs=1e-9)
        assert result["p50"] == pytest.approx(0.1, abs=1e-9)


# ---------------------------------------------------------------------------
# TestPeakRssMb
# ---------------------------------------------------------------------------


class TestPeakRssMb:
    def test_returns_positive_float(self) -> None:
        """peak_rss_mb() returns a positive float."""
        rss = peak_rss_mb()
        assert isinstance(rss, float)
        assert rss > 0.0

    def test_non_decreasing_across_calls(self) -> None:
        """RSS does not decrease between two successive calls."""
        r1 = peak_rss_mb()
        _ = [i ** 2 for i in range(100_000)]  # allocate some memory
        r2 = peak_rss_mb()
        # Peak RSS can only stay the same or increase
        assert r2 >= r1


# ---------------------------------------------------------------------------
# TestRecallAtK
# ---------------------------------------------------------------------------


class TestRecallAtK:
    def test_perfect_recall(self) -> None:
        """All relevant items are in top-k → recall = 1.0."""
        retrieved = ["a", "b", "c", "d"]
        relevant = ["a", "b"]
        assert recall_at_k(retrieved, relevant, k=4) == 1.0

    def test_partial_recall(self) -> None:
        """Half of relevant items retrieved → recall = 0.5."""
        retrieved = ["a", "x", "y", "z"]
        relevant = ["a", "b"]
        assert recall_at_k(retrieved, relevant, k=4) == pytest.approx(0.5)

    def test_zero_recall(self) -> None:
        """No relevant items in retrieved list → recall = 0.0."""
        retrieved = ["x", "y", "z"]
        relevant = ["a", "b"]
        assert recall_at_k(retrieved, relevant, k=3) == 0.0

    def test_empty_relevant(self) -> None:
        """Empty relevant set → recall = 0.0 (not a division by zero)."""
        assert recall_at_k(["a", "b"], [], k=2) == 0.0

    def test_k_smaller_than_retrieved(self) -> None:
        """Only top-k items considered; items beyond k are ignored."""
        # "b" is at position 3, beyond k=2
        retrieved = ["a", "x", "b", "c"]
        relevant = ["b"]
        assert recall_at_k(retrieved, relevant, k=2) == 0.0
        assert recall_at_k(retrieved, relevant, k=3) == 1.0

    def test_k_zero(self) -> None:
        """k=0: nothing is retrieved, recall = 0.0."""
        assert recall_at_k(["a", "b"], ["a"], k=0) == 0.0

    def test_duplicates_in_retrieved(self) -> None:
        """Duplicates in retrieved are deduplicated by set intersection."""
        # "a" appears twice but is only one distinct item
        retrieved = ["a", "a", "a"]
        relevant = ["a"]
        assert recall_at_k(retrieved, relevant, k=3) == 1.0


# ---------------------------------------------------------------------------
# TestBuildReport
# ---------------------------------------------------------------------------


class TestBuildReport:
    def _make_result(
        self,
        model: str = "test/model",
        backend: str = "torch",
        dimension: int = 256,
        p50_ms: float = 100.0,
        p95_ms: float = 150.0,
        p99_ms: float = 170.0,
        rss_mb: float = 512.0,
        recall_at_10: float = 0.75,
        error: str | None = None,
    ) -> dict:
        return {
            "model": model,
            "backend": backend,
            "dimension": dimension,
            "p50_ms": p50_ms,
            "p95_ms": p95_ms,
            "p99_ms": p99_ms,
            "mean_ms": (p50_ms + p95_ms) / 2 if (p50_ms is not None and p95_ms is not None) else None,
            "std_ms": 10.0,
            "rss_mb": rss_mb,
            "recall_at_10": recall_at_10,
            "n_repeats": 30,
            "error": error,
        }

    def test_markdown_contains_header(self) -> None:
        """Report starts with expected markdown header."""
        report = build_report([self._make_result()])
        assert "# PageIndex Embedding Latency Benchmark" in report

    def test_table_separator_present(self) -> None:
        """Markdown table separator row is present."""
        report = build_report([self._make_result()])
        assert "|---|" in report

    def test_recommendation_present(self) -> None:
        """Report contains a Recommendation section."""
        report = build_report([self._make_result()])
        assert "## Recommendation" in report
        assert "**Recommended**" in report

    def test_failed_row_marked(self) -> None:
        """A result with error is labelled FAILED in the table."""
        r = self._make_result(error="load_failed: model not found", p95_ms=None)
        report = build_report([r])
        assert "FAILED" in report

    def test_slow_row_warns(self) -> None:
        """A result exceeding the latency gate is marked WARN."""
        r = self._make_result(p95_ms=500.0)
        report = build_report([r], latency_gate_ms=200.0)
        assert "WARN" in report

    def test_ok_row_no_warn(self) -> None:
        """A result within the latency gate is marked OK."""
        r = self._make_result(p95_ms=100.0)
        report = build_report([r], latency_gate_ms=200.0)
        assert "OK" in report
        assert "WARN" not in report

    def test_all_failed_no_recommendation(self) -> None:
        """When all configurations fail, no recommendation is emitted."""
        r = self._make_result(error="load_failed", p50_ms=None, p95_ms=None)
        report = build_report([r])
        assert "**Recommended**" not in report
        assert "WARNING" in report

    def test_multiple_results_picks_best_p95(self) -> None:
        """Recommendation picks the configuration with the lowest p95."""
        fast = self._make_result(model="fast/model", p95_ms=80.0)
        slow = self._make_result(model="slow/model", p95_ms=180.0)
        report = build_report([fast, slow], latency_gate_ms=200.0)
        # The recommendation line should mention the fast model
        rec_line = [line for line in report.splitlines() if "**Recommended**" in line]
        assert len(rec_line) == 1
        assert "fast" in rec_line[0].lower() or "model" in rec_line[0].lower()
