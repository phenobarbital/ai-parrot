"""Latency benchmarks for the deterministic groundedness scorer (FEAT-398).

Spec §4 Performance Benchmarks / §5 acceptance criterion: the scorer must
stay orders of magnitude under an LLM-judge groundedness check (Guardrails
publishes P50 ~7s / P95 ~43s for the equivalent check — see the brainstorm's
Appendix A). These benchmarks gate on that budget directly with raw
``time.perf_counter()`` — no external benchmark library, per this task's
Codebase Contract (``pytest-benchmark`` is available elsewhere in the repo
for other suites, but is deliberately NOT used here).

Unlike ``tests/benchmarks/test_guardrails_pipeline_perf.py`` (which uses the
``pytest-benchmark`` plugin and is skipped without ``--benchmark-only``),
these tests run in normal ``pytest`` invocations — they assert a hard
latency gate directly (spec §5 AC), not an informational timing report.

Run with::

    pytest tests/benchmarks/test_groundedness_perf.py -v -s
"""
from __future__ import annotations

import time

from parrot.models.basic import ToolCall
from parrot.security.groundedness.evidence import EvidenceIndex
from parrot.security.groundedness.policy import GroundednessPolicy
from parrot.security.groundedness.scorer import GroundednessScorer

_ITERATIONS = 1000


def _percentiles(durations_ms: list[float]) -> tuple[float, float, float]:
    """Return (p50, p99, max) from a list of millisecond durations."""
    ordered = sorted(durations_ms)
    p50 = ordered[int(len(ordered) * 0.50)]
    p99 = ordered[int(len(ordered) * 0.99)]
    return p50, p99, ordered[-1]


class TestGroundednessPerf:
    def test_typical_case_p99_under_10ms(self):
        """1 KB answer vs 3x2 KB evidence: p99 < 10 ms (spec §5 hard gate)."""
        policy = GroundednessPolicy()
        scorer = GroundednessScorer(policy)
        answer = "Revenue was $1,243,500 for Q2 2026. " * 25  # ~1 KB
        tool_calls = [
            ToolCall(
                id=str(i), name=f"tool_{i}", arguments={}, result="x" * 2048,
            )
            for i in range(3)
        ]
        evidence = EvidenceIndex.from_tool_calls(tool_calls, policy)

        durations: list[float] = []
        for _ in range(_ITERATIONS):
            start = time.perf_counter()
            scorer.score(answer, evidence)
            durations.append((time.perf_counter() - start) * 1000)

        p50, p99, worst = _percentiles(durations)
        print(
            f"\n[groundedness typical case] p50={p50:.3f}ms "
            f"p99={p99:.3f}ms max={worst:.3f}ms ({_ITERATIONS} iterations)"
        )
        assert p99 < 10.0, f"p99={p99:.2f}ms exceeds 10ms gate"

    def test_heavy_case_p99_under_50ms(self):
        """4 KB answer vs 10x4 KB evidence: p99 < 50 ms (informational gate)."""
        policy = GroundednessPolicy()
        scorer = GroundednessScorer(policy)
        answer = "Revenue was $1,243,500 for Q2 2026. " * 100  # ~4 KB
        tool_calls = [
            ToolCall(
                id=str(i), name=f"tool_{i}", arguments={}, result="x" * 4096,
            )
            for i in range(10)
        ]
        evidence = EvidenceIndex.from_tool_calls(tool_calls, policy)

        durations: list[float] = []
        for _ in range(_ITERATIONS):
            start = time.perf_counter()
            scorer.score(answer, evidence)
            durations.append((time.perf_counter() - start) * 1000)

        p50, p99, worst = _percentiles(durations)
        print(
            f"\n[groundedness heavy case] p50={p50:.3f}ms "
            f"p99={p99:.3f}ms max={worst:.3f}ms ({_ITERATIONS} iterations)"
        )
        assert p99 < 50.0, f"p99={p99:.2f}ms exceeds 50ms gate"
