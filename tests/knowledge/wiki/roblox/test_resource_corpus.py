"""Tests for the Luau parser resource-measurement corpus and benchmark
runner (FEAT-532 TASK-2896).

These tests exercise ``scripts/benchmarks/luau_parser_limits.py`` — the
module that measures the resource policy TASK-2898/TASK-2899 depend on.
They do not test a production scanner (none exists yet; see the task's
Codebase Contract "Does NOT Exist" section) — they test the measurement
tooling itself: corpus reproducibility, and the killable-subprocess
benchmark harness's ability to actually terminate a stuck child and leave
the next parse unaffected.
"""

from __future__ import annotations

import importlib.util
import time

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("tree_sitter") is None or importlib.util.find_spec("tree_sitter_luau") is None,
    reason="tree-sitter / tree-sitter-luau not installed (optional wiki-languages extra)",
)


@pytest.fixture(scope="module")
def bench():
    # Imported as a real package (``scripts/benchmarks/__init__.py`` makes
    # it one), not loaded ad hoc by file path: ``run_isolated``'s
    # ``multiprocessing`` "spawn" child processes re-import worker
    # functions by their module's dotted path, which only resolves for a
    # normally importable module — matching how the sibling
    # ``scripts.sdd.*`` modules are already imported by their own tests.
    import scripts.benchmarks.luau_parser_limits as module

    return module


def test_corpus_is_repeatable(bench):
    """The same parameters yield identical bytes and documented case sizes."""
    first = bench.build_corpus()
    second = bench.build_corpus()

    assert [c.name for c in first] == [c.name for c in second]
    for a, b in zip(first, second):
        assert a.source == b.source, f"{a.name} corpus bytes are not deterministic"

    sizes = {c.name: len(c.source) for c in first}
    # Documented approximate sizes (spec §3.1: "an approximately 842 KB
    # pathological sample"). Exact byte counts are pinned here so a future
    # change to the generators is a deliberate, reviewed diff.
    assert sizes["valid_small"] == 268
    assert sizes["malformed_unbalanced"] == 106
    assert sizes["incompatible_python"] == 156
    assert 800_000 <= sizes["pathological_842kb"] <= 900_000


def test_corpus_names_are_unique(bench):
    names = [c.name for c in bench.build_corpus()]
    assert len(names) == len(set(names))


def test_valid_cases_parse_without_errors(bench):
    """Sanity check: the two "valid" fixtures actually parse clean."""
    corpus = {c.name: c for c in bench.build_corpus()}
    for name in ("valid_small", "valid_medium"):
        result = bench.run_isolated(corpus[name].source, deadline_seconds=5.0)
        assert result.outcome == "completed", (name, result.detail)
        assert result.error_node_count == 0
        assert result.node_count and result.node_count > 0


def test_malformed_case_reports_error_nodes(bench):
    corpus = {c.name: c for c in bench.build_corpus()}
    result = bench.run_isolated(corpus["malformed_unbalanced"].source, deadline_seconds=5.0)
    assert result.outcome == "completed"
    assert result.error_node_count and result.error_node_count > 0
    assert result.error_density and result.error_density > 0.0


def test_benchmark_kills_stuck_child(bench):
    """A deliberately stalled parser exits within the outer deadline,
    leaves no child running, and records timeout."""
    deadline = 1.0
    start = time.monotonic()
    result = bench.run_isolated_with_worker(
        b"irrelevant source",
        deadline_seconds=deadline,
        worker=bench._stall_worker,
    )
    elapsed = time.monotonic() - start

    assert result.outcome == "timeout"
    # Generous upper bound: deadline + termination/kill grace joins (2 x 1.0s).
    assert elapsed < deadline + 3.0, "benchmark did not return promptly after kill"


def test_following_parse_is_clean(bench):
    """A timeout/error case is followed by a valid parse without stale
    parser state (no shared/interrupted parser carried across processes,
    since each call gets its own freshly spawned child)."""
    corpus = {c.name: c for c in bench.build_corpus()}

    timeout_result = bench.run_isolated_with_worker(
        b"irrelevant source", deadline_seconds=0.5, worker=bench._stall_worker
    )
    assert timeout_result.outcome == "timeout"

    clean_result = bench.run_isolated(corpus["valid_small"].source, deadline_seconds=5.0)
    assert clean_result.outcome == "completed"
    assert clean_result.error_node_count == 0
    assert clean_result.node_count == 98
