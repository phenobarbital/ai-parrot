"""Metric computation for the PageIndex embedding latency benchmark.

Provides latency percentiles, RSS memory tracking, and recall@k computation.
All functions are pure (no side-effects) and work on plain Python types so
they can be unit-tested without any ML dependencies.
"""
from __future__ import annotations

import resource
from typing import Sequence

import numpy as np


def latency_percentiles(timings: Sequence[float]) -> dict[str, float | int]:
    """Compute p50, p95, p99, mean, and std from a list of durations.

    Args:
        timings: Sequence of elapsed-time measurements in seconds.  Must
            contain at least one value.

    Returns:
        Dictionary with keys ``p50``, ``p95``, ``p99``, ``mean``, ``std``,
        and ``n`` (sample count).

    Raises:
        ValueError: If *timings* is empty.
    """
    if len(timings) == 0:
        raise ValueError("timings must not be empty")
    arr = np.array(timings, dtype=np.float64)
    return {
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "n": int(len(timings)),
    }


def peak_rss_mb() -> float:
    """Return the current peak resident set size in megabytes.

    Uses ``resource.getrusage(resource.RUSAGE_SELF)``.  On Linux the kernel
    reports in kilobytes; on macOS it reports in bytes.  This function
    normalises both to megabytes.

    Returns:
        Peak RSS in megabytes as a float.
    """
    import sys

    ru = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        # macOS: ru_maxrss is in bytes
        return ru.ru_maxrss / (1024 * 1024)
    # Linux: ru_maxrss is in kilobytes
    return ru.ru_maxrss / 1024


def recall_at_k(
    retrieved: Sequence[str],
    relevant: Sequence[str],
    k: int,
) -> float:
    """Compute Recall@k: fraction of relevant items found in the top-k results.

    Args:
        retrieved: Ordered list of retrieved item identifiers (node IDs or
            similar).  Only the first *k* items are considered.
        relevant: Ground-truth set of relevant item identifiers.
        k: Cut-off rank.

    Returns:
        Recall@k in ``[0.0, 1.0]``.  Returns ``0.0`` when *relevant* is
        empty.
    """
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0
    top_k = set(list(retrieved)[:k])
    return len(top_k & relevant_set) / len(relevant_set)
