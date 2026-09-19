"""S3 gate tests: fast strategy/metric checks (always) + corpus evaluation (PARROT_SPIKE_FULL=1)."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

import pytest

from . import harness

FULL = os.environ.get("PARROT_SPIKE_FULL") == "1"


@pytest.fixture
def item() -> harness.Item:
    """One synthetic Item: 3 delivered refs (1 relevant, 1 not_relevant, 1 unknown), a cross-scope
    citation, and an evidence error signature that equals the relevant ref's signature."""
    relevant_tokens = frozenset({"retry", "backoff", "timeout"})
    not_relevant_tokens = frozenset({"unrelated", "topic"})

    mem_relevant = harness.DeliveredRef(
        memory_id="mem-relevant",
        content_version="v1",
        kind="episode",
        error_signature="ERR_TIMEOUT",
        lesson_tokens=relevant_tokens,
    )
    mem_not_relevant = harness.DeliveredRef(
        memory_id="mem-not-relevant",
        content_version="v1",
        kind="episode",
        error_signature=None,
        lesson_tokens=not_relevant_tokens,
    )
    mem_unknown = harness.DeliveredRef(
        memory_id="mem-unknown",
        content_version="v1",
        kind="brain",
        error_signature=None,
        lesson_tokens=frozenset(),
    )
    exposure = harness.Exposure(
        exposure_id="exp-1",
        attempt_or_turn_id="attempt-1",
        delivered=(mem_relevant, mem_not_relevant, mem_unknown),
        packed_sha256=harness.sha256_text("packed-content-1"),
    )
    evidence = harness.OutcomeEvidence(
        outcome_id="outcome-1",
        verified=True,
        success=False,
        first_attempt=True,
        correction_count=0,
        error_signature="ERR_TIMEOUT",
        recovery_refs=(),  # prose-equivalent tokens exist, but NO structural recovery ref
        cited=("mem-relevant", "mem-cross-scope-id"),
        tool_tokens=relevant_tokens,
        source="tool_runtime",
    )
    return harness.Item(
        item_id="item-1",
        provenance="synthetic",
        exposure=exposure,
        evidence=evidence,
        labels={"mem-relevant": "relevant", "mem-not-relevant": "not_relevant", "mem-unknown": "unknown"},
        judge="model:claude-sonnet-5",
        judged_at=datetime(2026, 9, 18, tzinfo=timezone.utc).isoformat(),
    )


def test_cited_drops_cross_scope_ids(item) -> None:
    out = harness.cited(item.exposure, item.evidence)
    assert all(mid in {r.memory_id for r in item.exposure.delivered} for mid in out)
    assert "mem-cross-scope-id" not in out
    assert out == ["mem-relevant"]


def test_recovery_linkage_ignores_prose_equality(item) -> None:
    # mem-relevant's lesson_tokens are identical to evidence.tool_tokens (prose-equivalent), and
    # overlap_tokens WOULD attribute it — but recovery_refs is empty, so recovery_linkage must not.
    assert item.evidence.recovery_refs == ()
    assert "mem-relevant" in harness.overlap_tokens(item.exposure, item.evidence)
    out = harness.recovery_linkage(item.exposure, item.evidence)
    assert out == []


def test_grade_row_precedence(item) -> None:
    base = item.evidence

    # Repeated signature -> AGAIN (verified failure, same nonempty normalized error signature).
    assert (
        harness.grade_row(
            base, attributed=True, memory_error_signature="ERR_TIMEOUT", recovered=False, overlap_only=False
        )
        == "again"
    )

    # Verified recovery via citation -> EASY.
    recovered_evidence = replace(base, success=True, recovery_refs=("mem-relevant",))
    assert (
        harness.grade_row(
            recovered_evidence, attributed=True, memory_error_signature=None, recovered=True, overlap_only=False
        )
        == "easy"
    )

    # Verified recovery via an overlap heuristic (not a citation) -> capped to GOOD.
    assert (
        harness.grade_row(
            recovered_evidence, attributed=True, memory_error_signature=None, recovered=True, overlap_only=True
        )
        == "good_capped"
    )

    # Verified success with confirmed corrections -> HARD.
    corrections_evidence = replace(base, success=True, correction_count=2, recovery_refs=())
    assert (
        harness.grade_row(
            corrections_evidence, attributed=True, memory_error_signature=None, recovered=False, overlap_only=False
        )
        == "hard"
    )

    # Verified success, first attempt, zero corrections -> GOOD.
    clean_evidence = replace(base, success=True, correction_count=0, first_attempt=True, recovery_refs=())
    assert (
        harness.grade_row(
            clean_evidence, attributed=True, memory_error_signature=None, recovered=False, overlap_only=False
        )
        == "good"
    )

    # Unverified outcome -> no_review, regardless of attribution.
    unverified_evidence = replace(base, verified=False)
    assert (
        harness.grade_row(
            unverified_evidence, attributed=True, memory_error_signature=None, recovered=False, overlap_only=False
        )
        == "no_review"
    )


def test_metrics_count_false_reinforcement(item) -> None:
    # A strategy that also attributes the not_relevant ref, under an evidence outcome that would
    # grade GOOD, must register false reinforcement and drop precision below 1.
    clean_evidence = replace(item.evidence, success=True, correction_count=0, first_attempt=True, recovery_refs=())
    reinforcing_item = replace(
        item,
        evidence=clean_evidence,
        strategy_outputs={"over_attributing": ["mem-relevant", "mem-not-relevant"]},
    )
    result = harness.metrics([reinforcing_item], "over_attributing")
    assert result["false_reinforcement"] > 0
    assert result["precision"] < 1.0


def test_metrics_ignores_unknown_labels(item) -> None:
    only_unknown_item = replace(item, strategy_outputs={"strat": ["mem-unknown"]})
    result = harness.metrics([only_unknown_item], "strat")
    assert result["precision"] == 0.0
    assert result["unknown_count"] == 1.0
    assert result["unknown_attributed"] == 1.0


@pytest.mark.skipif(not FULL, reason="set PARROT_SPIKE_FULL=1 to evaluate the 50-item corpus and write REPORT.md")
def test_corpus_evaluation_writes_report() -> None:
    items = harness.load_corpus()
    assert len(items) == 50

    strategy_names = ["cited", "overlap_tokens", "overlap_error_signature", "recovery_linkage", "combined"]
    results: dict[str, Any] = {
        "corpus": {
            "total": len(items),
            "real": sum(1 for i in items if i.provenance == "real"),
            "synthetic": sum(1 for i in items if i.provenance == "synthetic"),
            "judge": items[0].judge if items else "unknown",
        },
        "strategies": {},
    }
    for name in strategy_names:
        results["strategies"][name] = {}
        for cap in harness.CANDIDATE_CAPS:
            cap_key = "unbounded" if cap is None else str(cap)
            results["strategies"][name][cap_key] = harness.metrics(items, f"{name}@{cap_key}")

    commands = [
        "PARROT_SPIKE_FULL=1 python3 -m pytest "
        "packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/test_s3_harness.py"
        "::test_corpus_evaluation_writes_report -q"
    ]
    limitations = [
        "No coder-review/coder-feedback ledger data or episodic-store dumps were available in "
        "this worktree to mine real traces (no sdd/state ledger sqlite plane, no episodic backend "
        "snapshot committed); the corpus is 100% synthetic (0 real, 50 synthetic), each item hand "
        "-constructed to exercise one grade-table branch (again/easy/hard/good/no_review) and one "
        "attribution edge case (cross-scope citation, prose-equivalent-but-unlinked recovery, "
        "token-overlap collision). This is a declared gate limitation per spec §3 G3 "
        "'Insufficient real trace coverage is a gate limitation' — numbers below characterize the "
        "candidate strategies' behavior on controlled scenarios, not empirical field precision.",
        "Overlap-token threshold (0.3) and candidate caps (1/3/5/unbounded) are experiment inputs "
        "per spec §2, not frozen defaults; see amendment.md for the proposed freeze.",
    ]
    report_path = harness.write_report(results, commands=commands, limitations=limitations)
    assert report_path.exists()
    assert (harness.SPIKE_DIR / "metrics.json").exists()
