"""S1 spike harness: reference loader, traces, metrics and report writer."""

from __future__ import annotations

import importlib
import json
import logging
import math
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pydantic

from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedbackStore

from . import candidate

logger = logging.getLogger(__name__)
REPO_ROOT = (
    Path(__file__).resolve().parents[7]
)  # …/spikes/s1_fsrs/harness.py → repo root (only for CoderFeedbackStore.from_root)
SPIKE_DIR = (
    Path(__file__).resolve().parent
)  # coder-owned spike package dir — sdd-coder fidelity gate forbids commits under sdd/
REFERENCE_DIR = SPIKE_DIR / "reference"
REFERENCE_COMMIT = "9446cb06605c597a063aeee49f7d188d42e34dc2"  # py-fsrs v6.3.2, MIT

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def load_reference() -> Any:
    """Import the vendored `fsrs` package (never the PyPI one) and return the module."""
    if str(REFERENCE_DIR) not in sys.path:
        sys.path.insert(0, str(REFERENCE_DIR))
    module = importlib.import_module("fsrs")
    logger.info("S1 reference loaded from %s", Path(module.__file__).parent)
    return module


@dataclass(frozen=True)
class ReviewEvent:
    """One graded review at an aware UTC instant."""

    at: datetime
    grade: int


def review_sequences(seed: int, count: int) -> list[list[ReviewEvent]]:
    """Seeded sequences mixing same-day, multi-day and long-gap reviews across all grades."""
    rng = random.Random(seed)
    grades = [1, 2, 3, 4]
    gap_choices: list[tuple[str, tuple[int, int]]] = [
        ("minutes", (1, 50)),
        ("hours", (1, 20)),
        ("days_short", (1, 3)),
        ("days_long", (7, 60)),
    ]
    sequences: list[list[ReviewEvent]] = []
    for _ in range(count):
        n_steps = rng.randint(4, 12)
        now = T0
        events: list[ReviewEvent] = []
        # Guarantee every grade appears at least once, then pad the rest randomly.
        guaranteed = grades.copy()
        rng.shuffle(guaranteed)
        for step in range(n_steps):
            grade = guaranteed[step] if step < len(guaranteed) else rng.choice(grades)
            unit, (lo, hi) = rng.choice(gap_choices)
            amount = rng.randint(lo, hi)
            if unit == "minutes":
                now = now + timedelta(minutes=amount)
            elif unit == "hours":
                now = now + timedelta(hours=amount)
            else:  # days_short | days_long
                # A pure whole-day timedelta would make 'days-v1' and 'hours-v1' numerically
                # identical (both reduce to the same integer day count), defeating the point of
                # measuring the two policies side by side — add a sub-day remainder so the whole-day
                # (reference-exact) and fractional-day (candidate variant) elapsed times genuinely differ.
                now = now + timedelta(days=amount, minutes=rng.randint(0, 23 * 60 + 59))
            events.append(ReviewEvent(at=now, grade=grade))
        sequences.append(events)
    return sequences


def parity_rows(
    fsrs: Any, sequences: list[list[ReviewEvent]], w: tuple[float, ...], *, time_policy: str
) -> list[dict[str, float]]:
    """Replay each sequence through reference Scheduler(enable_fuzzing=False) and candidate; return per-step deltas."""
    scheduler = fsrs.Scheduler(parameters=w, enable_fuzzing=False)
    rows: list[dict[str, float]] = []
    for seq_idx, events in enumerate(sequences):
        card = fsrs.Card()
        cand_state: candidate.CandidateState | None = None
        for step_idx, event in enumerate(events):
            ref_r = scheduler.get_card_retrievability(card, event.at) if card.last_review is not None else None
            cand_r = (
                candidate.retrievability(cand_state, event.at, w, time_policy=time_policy)
                if cand_state is not None
                else None
            )
            card, _ = scheduler.review_card(card, fsrs.Rating(event.grade), review_datetime=event.at)
            if cand_state is None:
                cand_state = candidate.initial_state(candidate.Grade(event.grade), w, event.at)
            else:
                cand_state = candidate.transition(
                    cand_state, candidate.Grade(event.grade), w, event.at, time_policy=time_policy
                )

            delta_stability = abs(card.stability - cand_state.stability)
            delta_difficulty = abs(card.difficulty - cand_state.difficulty)
            delta_retrievability = abs(ref_r - cand_r) if (ref_r is not None and cand_r is not None) else None

            rows.append(
                {
                    "sequence": seq_idx,
                    "step": step_idx,
                    "time_policy": time_policy,
                    "delta_stability": delta_stability,
                    "delta_difficulty": delta_difficulty,
                    "delta_retrievability": delta_retrievability,
                }
            )

            if time_policy == "days-v1":
                # The reference is exact only under its own (whole-day) time policy — AC03.
                assert (
                    delta_stability < 1e-9
                ), f"stability parity failed seq={seq_idx} step={step_idx}: {delta_stability}"
                assert (
                    delta_difficulty < 1e-9
                ), f"difficulty parity failed seq={seq_idx} step={step_idx}: {delta_difficulty}"
                if delta_retrievability is not None:
                    assert (
                        delta_retrievability < 1e-9
                    ), f"retrievability parity failed seq={seq_idx} step={step_idx}: {delta_retrievability}"
            # 'hours-v1' is a candidate variant with no reference counterpart — deltas are recorded, not asserted.
    return rows


def synthetic_agent_trace(seed: int, days: int = 30) -> list[dict[str, Any]]:
    """30-day generic-agent trace: lessons created at minutes-to-hours cadence with verified outcomes."""
    rng = random.Random(seed)
    window_end = T0 + timedelta(days=days)
    n_lessons = 60
    trace: list[dict[str, Any]] = []
    for i in range(n_lessons):
        created_at = T0 + timedelta(days=rng.uniform(0, days))
        importance = rng.randint(1, 10)
        n_reviews = rng.choices([0, 1, 2, 3, 4], weights=[0.25, 0.30, 0.25, 0.15, 0.05])[0]
        reviews: list[dict[str, Any]] = []
        cursor = created_at
        for _ in range(n_reviews):
            cursor = cursor + timedelta(minutes=rng.randint(5, 24 * 60))
            if cursor > window_end:
                break
            grade = rng.choices([1, 2, 3, 4], weights=[0.15, 0.15, 0.5, 0.2])[0]
            reviews.append({"at": cursor, "grade": grade})
        prevented_recurrence = bool(reviews) and any(r["grade"] >= 3 for r in reviews) and rng.random() < 0.4
        trace.append(
            {
                "lesson_id": f"lesson-{i:03d}",
                "created_at": created_at,
                "importance": importance,
                "reviews": reviews,
                "prevented_recurrence": prevented_recurrence,
            }
        )
    return trace


def ledger_signal_cadence(root: Path) -> dict[str, Any]:
    """Observed cadence/recurrence from CoderFeedbackStore.from_root(root)._read(); NO grades are derived."""
    try:
        rows = CoderFeedbackStore.from_root(root)._read()
    except Exception as exc:  # pragma: no cover - defensive: ledger plane may not exist in every environment
        logger.warning("S1 ledger cadence unavailable: %s", exc)
        return {"rows": 0, "note": "ledger unavailable"}

    if not rows:
        return {"rows": 0, "note": "ledger unavailable"}

    timestamps = sorted(timestamp for timestamp, _feedback in rows)
    patterns = {feedback.pattern for _timestamp, feedback in rows}
    return {
        "rows": len(rows),
        "patterns": len(patterns),
        "first_seen": timestamps[0],
        "last_seen": timestamps[-1],
        "note": "no attribution -> no grades",
    }


def _rank(values: list[float]) -> list[float]:
    """Average-tie ranks, ascending (rank 1 = smallest value)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def _spearman(a: list[float], b: list[float]) -> float | None:
    """Spearman rank correlation with average-tie ranks; None when undefined (n<2 or zero variance)."""
    n = len(a)
    if n < 2:
        return None
    ra, rb = _rank(a), _rank(b)
    mean_a, mean_b = sum(ra) / n, sum(rb) / n
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(ra, rb))
    var_a = sum((x - mean_a) ** 2 for x in ra)
    var_b = sum((y - mean_b) ** 2 for y in rb)
    if var_a == 0 or var_b == 0:
        return None
    return cov / math.sqrt(var_a * var_b)


def _lexicographic_ranks(keys: list[tuple[float, ...]]) -> list[float]:
    """Rank positions (1=best) induced by `ranked.sort(key=..., reverse=True)`-style tuple ordering."""
    order = sorted(range(len(keys)), key=lambda i: keys[i], reverse=True)
    ranks = [0.0] * len(keys)
    for position, idx in enumerate(order):
        ranks[idx] = float(position + 1)
    return ranks


def calibration_metrics(
    trace: list[dict[str, Any]], w: tuple[float, ...], *, time_policy: str, forget_threshold: float
) -> dict[str, Any]:
    """Forgotten-before-first-review, useful-retention, stale-persistence, rank correlation, 30-day GOOD survival.

    Modeling choice (documented for owner review): lesson *creation* is treated as an implicit
    "GOOD" encoding event (``candidate.initial_state(Grade.GOOD, ...)``); subsequent trace
    ``reviews`` are later touches/verified-outcomes that reinforce or weaken that encoding.
    "Relevance" (spec's ``relevance × retrievability × (1 + importance/10)``) has no query
    context in this offline calibration, so it is proxied as ``min(1.0, len(reviews) / 4)`` —
    called out explicitly so the owner can accept, adjust, or reject the proxy in amendment.md.
    """
    if not trace:
        return {"note": "empty trace"}

    window_start = min(lesson["created_at"] for lesson in trace)
    window_end = window_start + timedelta(days=30)

    forgotten_flags: list[bool] = []
    prevented_survival: list[bool] = []
    stale_flags: list[bool] = []
    good_survival: list[bool] = []
    new_scores: list[float] = []
    baseline_keys: list[tuple[float, float, float]] = []

    for lesson in trace:
        created_at = lesson["created_at"]
        reviews = lesson["reviews"]
        importance = lesson["importance"]

        state = candidate.initial_state(candidate.Grade.GOOD, w, created_at)

        if reviews:
            r_before_first_review = candidate.retrievability(state, reviews[0]["at"], w, time_policy=time_policy)
            forgotten_flags.append(r_before_first_review < forget_threshold)

        for review in reviews:
            state = candidate.transition(
                state, candidate.Grade(review["grade"]), w, review["at"], time_policy=time_policy
            )

        final_r = candidate.retrievability(state, window_end, w, time_policy=time_policy)

        if lesson["prevented_recurrence"]:
            prevented_survival.append(final_r >= forget_threshold)

        if not reviews and (window_end - created_at) >= timedelta(days=30):
            stale_flags.append(final_r >= forget_threshold)

        if any(r["grade"] == int(candidate.Grade.GOOD) for r in reviews):
            good_survival.append(final_r >= forget_threshold)

        relevance_proxy = min(1.0, len(reviews) / 4)
        new_scores.append(relevance_proxy * final_r * (1 + importance / 10))

        scope_score_proxy = 2 if importance >= 8 else (1 if importance >= 5 else 0)
        baseline_keys.append((scope_score_proxy, len(reviews), created_at.timestamp()))

    baseline_ranks = _lexicographic_ranks(baseline_keys)
    rank_correlation = _spearman(new_scores, baseline_ranks)

    def _fraction(flags: list[bool]) -> float | None:
        return (sum(flags) / len(flags)) if flags else None

    return {
        "time_policy": time_policy,
        "forget_threshold": forget_threshold,
        "n_lessons": len(trace),
        "fraction_forgotten_before_first_review": _fraction(forgotten_flags),
        "n_lessons_with_reviews": len(forgotten_flags),
        "fraction_prevented_recurrence_retained": _fraction(prevented_survival),
        "n_prevented_recurrence_lessons": len(prevented_survival),
        "fraction_stale_persistence": _fraction(stale_flags),
        "n_stale_eligible_lessons": len(stale_flags),
        "rank_correlation_new_score_vs_baseline": rank_correlation,
        "fraction_good_review_survives_30d": _fraction(good_survival),
        "n_good_review_lessons": len(good_survival),
    }


def write_report(metrics: dict[str, Any], *, commands: list[str], provenance: dict[str, Any]) -> Path:
    """Write metrics.json and REPORT.md under SPIKE_DIR; return REPORT.md path."""
    SPIKE_DIR.mkdir(parents=True, exist_ok=True)
    (SPIKE_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True, default=str) + "\n")

    lines: list[str] = []
    lines.append("# S1 FSRS parity and 30-day calibration — REPORT (TASK-3382)")
    lines.append("")
    lines.append("## Commands")
    lines.append("")
    for command in commands:
        lines.append(f"```\n{command}\n```")
    lines.append("")
    lines.append("## Versions")
    lines.append("")
    lines.append(f"- python: {sys.version.split()[0]}")
    lines.append(f"- pydantic: {pydantic.VERSION}")
    lines.append(f"- py-fsrs reference commit: {REFERENCE_COMMIT} (v6.3.2, MIT)")
    lines.append("")
    lines.append("## Data provenance")
    lines.append("")
    for key, value in provenance.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Raw metrics (per time policy)")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(metrics, indent=2, sort_keys=True, default=str))
    lines.append("```")
    lines.append("")
    lines.append("## Pass/Fail per check")
    lines.append("")
    for policy_key in ("days-v1", "hours-v1"):
        policy_metrics = metrics.get(policy_key)
        if not isinstance(policy_metrics, dict):
            continue
        good_survival = policy_metrics.get("fraction_good_review_survives_30d")
        status = "PASS" if good_survival == 1.0 else ("FAIL" if good_survival is not None else "PENDING")
        lines.append(
            f"- [{policy_key}] non-lapsed lesson with >=1 GOOD review survives 30 days: {status} ({good_survival})"
        )
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "- Ledger history provides recurrence/timestamps only — never grades (spec §2); "
        "the rank-correlation baseline and 'relevance' proxy are documented interpretive choices, not "
        "approved formulas."
    )
    lines.append(
        "- Stale-persistence eligibility requires a lesson dormant for the *entire* 30-day window, so few "
        "synthetic lessons qualify inside a 30-day trace — the metric's n is small by construction."
    )
    lines.append("")
    lines.append("## Proposed amendment")
    lines.append("")
    lines.append("See `amendment.md` in this directory (owner review required before M1 starts).")

    report_path = SPIKE_DIR / "REPORT.md"
    report_path.write_text("\n".join(lines) + "\n")
    return report_path
