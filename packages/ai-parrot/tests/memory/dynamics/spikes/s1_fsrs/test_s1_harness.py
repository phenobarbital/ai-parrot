"""S1 gate tests: fast parity (always) + full calibration (PARROT_SPIKE_FULL=1)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from . import candidate, harness

FULL = os.environ.get("PARROT_SPIKE_FULL") == "1"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def fsrs():
    if not harness.REFERENCE_DIR.exists():
        pytest.skip("vendored py-fsrs reference not present — run Step 1 of TASK-3382")
    return harness.load_reference()


def test_reference_pin(fsrs) -> None:
    """The vendored reference has 21 default parameters and fuzzing can be disabled."""
    from fsrs.scheduler import DEFAULT_PARAMETERS  # vendored

    assert len(DEFAULT_PARAMETERS) == 21
    assert fsrs.Scheduler(enable_fuzzing=False) is not None


@pytest.mark.parametrize("grade", list(candidate.Grade))
def test_initial_state_parity(fsrs, grade) -> None:
    """First review at T0, all four grades: candidate matches reference within 1e-9."""
    from fsrs.scheduler import DEFAULT_PARAMETERS

    card = fsrs.Card()
    card, _ = fsrs.Scheduler(enable_fuzzing=False).review_card(card, fsrs.Rating(grade.value), review_datetime=T0)
    candidate_state = candidate.initial_state(grade, DEFAULT_PARAMETERS, T0)

    assert abs(card.stability - candidate_state.stability) < 1e-9
    assert abs(card.difficulty - candidate_state.difficulty) < 1e-9


def test_sequence_parity_days_policy(fsrs) -> None:
    """200 seeded sequences (all grades, same-day + long gaps) replay with < 1e-9 max delta."""
    from fsrs.scheduler import DEFAULT_PARAMETERS

    sequences = harness.review_sequences(seed=571, count=200)
    rows = harness.parity_rows(fsrs, sequences, DEFAULT_PARAMETERS, time_policy="days-v1")

    assert rows
    assert max(row["delta_stability"] for row in rows) < 1e-9
    assert max(row["delta_difficulty"] for row in rows) < 1e-9


def test_same_day_clamp_and_stability_floor(fsrs) -> None:
    """Same-day branch matches the reference exactly; a lapse after a long gap never breaches the floor."""
    from fsrs.scheduler import DEFAULT_PARAMETERS

    w = DEFAULT_PARAMETERS
    scheduler = fsrs.Scheduler(parameters=w, enable_fuzzing=False)

    # First review, then a same-day (minutes-later) second review.
    card = fsrs.Card()
    card, _ = scheduler.review_card(card, fsrs.Rating(3), review_datetime=T0)
    state = candidate.initial_state(candidate.Grade.GOOD, w, T0)

    second_at = T0 + timedelta(minutes=5)
    card, _ = scheduler.review_card(card, fsrs.Rating(3), review_datetime=second_at)
    state = candidate.transition(state, candidate.Grade.GOOD, w, second_at, time_policy="days-v1")

    assert abs(card.stability - state.stability) < 1e-9
    assert state.stability >= candidate.STABILITY_MIN

    # A lapse (AGAIN) after a long gap must never push stability below the floor.
    long_gap_at = second_at + timedelta(days=90)
    state = candidate.transition(state, candidate.Grade.AGAIN, w, long_gap_at, time_policy="days-v1")
    assert state.stability >= candidate.STABILITY_MIN


def test_retrievability_non_increasing() -> None:
    """R(t) is non-increasing in t for both time policies; R == 1.0 when last_review is None."""
    from fsrs.scheduler import DEFAULT_PARAMETERS as w  # vendored constant, no reference call needed here

    fresh_state = candidate.CandidateState(stability=0.0, difficulty=0.0, last_review=None)
    for policy in ("days-v1", "hours-v1"):
        assert candidate.retrievability(fresh_state, T0, w, time_policy=policy) == 1.0

    state = candidate.initial_state(candidate.Grade.GOOD, w, T0)
    for policy in ("days-v1", "hours-v1"):
        previous = None
        for offset_days in range(60):
            now = T0 + timedelta(days=offset_days)
            current = candidate.retrievability(state, now, w, time_policy=policy)
            if previous is not None:
                assert current <= previous + 1e-12
            previous = current


@pytest.mark.skipif(not FULL, reason="set PARROT_SPIKE_FULL=1 to run the 30-day calibration and write REPORT.md")
def test_full_calibration_writes_report(fsrs) -> None:
    """Run the synthetic trace + ledger cadence for both policies and write REPORT.md/metrics.json."""
    from fsrs.scheduler import DEFAULT_PARAMETERS as w

    forget_threshold = 0.2
    trace = harness.synthetic_agent_trace(seed=571, days=30)
    ledger_cadence = harness.ledger_signal_cadence(harness.REPO_ROOT)

    metrics: dict[str, object] = {}
    for policy in ("days-v1", "hours-v1"):
        metrics[policy] = harness.calibration_metrics(trace, w, time_policy=policy, forget_threshold=forget_threshold)
    metrics["ledger_cadence"] = ledger_cadence
    metrics["source_pass_check"] = {
        policy: metrics[policy].get("fraction_good_review_survives_30d") for policy in ("days-v1", "hours-v1")
    }

    report_path = harness.write_report(
        metrics,
        commands=[
            "PARROT_SPIKE_FULL=1 pytest packages/ai-parrot/tests/memory/dynamics/spikes/s1_fsrs/test_s1_harness.py -q -s"
        ],
        provenance={
            "synthetic_trace": "seeded generic-agent trace, seed=571, 30 days, 60 lessons",
            "ledger_signal": ledger_cadence,
        },
    )

    assert report_path.exists()
    assert (harness.SPIKE_DIR / "metrics.json").exists()
