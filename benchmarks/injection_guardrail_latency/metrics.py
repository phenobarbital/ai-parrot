"""Latency, memory, and detection-quality metrics.

Pure functions over plain Python types — no ML dependency, unit-testable
in isolation. Latency/RSS helpers mirror
``benchmarks/pageindex_embedding_latency/metrics.py``; the classification
and escalation helpers are specific to this benchmark.
"""
from __future__ import annotations

import resource
import sys
from collections.abc import Sequence

# ---------------------------------------------------------------------------
# Latency
# ---------------------------------------------------------------------------


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile of an already-sorted list.

    Args:
        sorted_values: Ascending values; must be non-empty.
        pct: Percentile in ``[0, 100]``.

    Returns:
        The value at the nearest rank.
    """
    if not sorted_values:
        raise ValueError("sorted_values must not be empty")
    rank = max(1, min(len(sorted_values), round(pct / 100.0 * len(sorted_values) + 0.5)))
    return sorted_values[rank - 1]


def latency_percentiles(timings: Sequence[float]) -> dict[str, float]:
    """Compute p50/p95/p99/mean/max from per-call durations.

    Args:
        timings: Durations in **seconds**. Must be non-empty.

    Returns:
        Dict with ``p50_ms``, ``p95_ms``, ``p99_ms``, ``mean_ms``,
        ``max_ms``, and ``n``.

    Raises:
        ValueError: If *timings* is empty.
    """
    if len(timings) == 0:
        raise ValueError("timings must not be empty")
    ordered = sorted(float(t) for t in timings)
    total = sum(ordered)
    return {
        "p50_ms": _percentile(ordered, 50) * 1000,
        "p95_ms": _percentile(ordered, 95) * 1000,
        "p99_ms": _percentile(ordered, 99) * 1000,
        "mean_ms": (total / len(ordered)) * 1000,
        "max_ms": ordered[-1] * 1000,
        "n": float(len(ordered)),
    }


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def peak_rss_mb() -> float:
    """Peak resident set size of this process, in megabytes.

    ``ru_maxrss`` is kilobytes on Linux and bytes on macOS; both are
    normalised here. Peak RSS is monotonic for the process lifetime, so it
    only attributes memory to a single model when the harness runs one
    backend per process (``--isolate``).
    """
    ru = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return ru.ru_maxrss / (1024 * 1024)
    return ru.ru_maxrss / 1024


def current_rss_mb() -> float:
    """Current (not peak) resident set size in megabytes.

    Read from ``/proc/self/statm`` on Linux so a before/after delta can
    attribute memory to one model load even in a shared process. Falls
    back to :func:`peak_rss_mb` where ``/proc`` is unavailable.
    """
    try:
        with open("/proc/self/statm", "r", encoding="ascii") as handle:
            pages = int(handle.read().split()[1])
        return pages * resource.getpagesize() / (1024 * 1024)
    except (OSError, IndexError, ValueError):
        return peak_rss_mb()


# ---------------------------------------------------------------------------
# Detection quality
# ---------------------------------------------------------------------------


def confusion(
    scores: Sequence[float],
    labels: Sequence[int],
    threshold: float,
) -> dict[str, int]:
    """Confusion counts for ``score >= threshold`` as the positive rule.

    Args:
        scores: Per-sample detector scores.
        labels: Per-sample ground truth (``1`` = injection).
        threshold: Decision threshold.

    Returns:
        Dict with ``tp``, ``fp``, ``tn``, ``fn``.
    """
    tp = fp = tn = fn = 0
    for score, label in zip(scores, labels):
        predicted = 1 if score >= threshold else 0
        if predicted == 1 and label == 1:
            tp += 1
        elif predicted == 1 and label == 0:
            fp += 1
        elif predicted == 0 and label == 0:
            tn += 1
        else:
            fn += 1
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def quality(
    scores: Sequence[float],
    labels: Sequence[int],
    threshold: float,
) -> dict[str, float]:
    """Precision / recall / F1 / accuracy at a fixed threshold.

    Args:
        scores: Per-sample detector scores.
        labels: Per-sample ground truth (``1`` = injection).
        threshold: Decision threshold.

    Returns:
        Dict with ``precision``, ``recall``, ``f1``, ``accuracy``, plus the
        raw confusion counts and the ``threshold`` used.
    """
    counts = confusion(scores, labels, threshold)
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    total = sum(counts.values())
    accuracy = (counts["tp"] + counts["tn"]) / total if total else 0.0
    return {
        "threshold": threshold,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": accuracy,
        **{k: float(v) for k, v in counts.items()},
    }


def sweep_thresholds(
    scores: Sequence[float],
    labels: Sequence[int],
    candidates: Sequence[float],
) -> list[dict[str, float]]:
    """Evaluate :func:`quality` at each candidate threshold.

    Args:
        scores: Per-sample detector scores.
        labels: Per-sample ground truth.
        candidates: Thresholds to evaluate.

    Returns:
        One :func:`quality` dict per candidate, in the given order.
    """
    return [quality(scores, labels, t) for t in candidates]


def best_threshold(sweep: Sequence[dict[str, float]]) -> dict[str, float] | None:
    """Pick the highest-F1 entry from a threshold sweep.

    Ties break toward the *higher* threshold (fewer false positives),
    which matches how a production guardrail should be tuned.

    Args:
        sweep: Output of :func:`sweep_thresholds`.

    Returns:
        The winning entry, or ``None`` when *sweep* is empty.
    """
    if not sweep:
        return None
    return max(sweep, key=lambda entry: (entry["f1"], entry["threshold"]))


# ---------------------------------------------------------------------------
# Tiering
# ---------------------------------------------------------------------------


def escalation_rate(
    cheap_decided: Sequence[bool],
) -> float:
    """Fraction of samples the cheap tiers could **not** decide.

    Args:
        cheap_decided: One flag per sample — ``True`` when a cheap tier
            reached a confident verdict (either "clearly an attack" or
            "clearly benign") and the expensive classifier can be skipped.

    Returns:
        Escalation rate in ``[0.0, 1.0]``. ``0.0`` means the classifier
        never runs.
    """
    if not cheap_decided:
        return 0.0
    return sum(1 for decided in cheap_decided if not decided) / len(cheap_decided)


def effective_latency_ms(
    tier_costs_ms: Sequence[float],
    escalation: float,
    classifier_cost_ms: float,
) -> float:
    """Expected per-turn cost of a tiered pipeline.

    Args:
        tier_costs_ms: Per-call cost of each always-run cheap tier.
        escalation: Fraction of turns that reach the classifier
            (see :func:`escalation_rate`).
        classifier_cost_ms: Per-call cost of the expensive tier.

    Returns:
        Expected milliseconds per turn.
    """
    return sum(tier_costs_ms) + escalation * classifier_cost_ms
