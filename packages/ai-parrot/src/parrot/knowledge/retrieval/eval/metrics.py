"""Reference-based metrics for the evaluation harness (spec §7).

**No LLM-as-judge anywhere in this module or package** — §7 rules it out
explicitly: "LLM-as-judge evaluation in this literature suffers documented
position, length, and trial biases severe enough to flip reported win
rates; narrow margins from such judging are not evidence." Every metric
here is a deterministic computation over labelled ground truth.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from parrot.knowledge.retrieval.classifier import QueryClass

logger = logging.getLogger(__name__)


class ClassMetrics(BaseModel):
    """Precision/recall for one `QueryClass` (spec §7).

    Attributes:
        query_class: Which class this is for.
        precision: Of queries the classifier routed to this class, the
            fraction whose true label was also this class.
        recall: Of queries whose true label is this class, the fraction
            the classifier actually routed here.
        support: Number of golden-set queries with this true label.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    query_class: QueryClass
    precision: float
    recall: float
    support: int


def precision_recall_per_class(
    predictions: Sequence[tuple[QueryClass, QueryClass]],
) -> dict[QueryClass, ClassMetrics]:
    """Compute per-class precision/recall over `(predicted, expected)` pairs.

    Args:
        predictions: One `(predicted_class, expected_class)` tuple per
            golden-set query.

    Returns:
        ``QueryClass -> ClassMetrics`` for every class that appears as
        either a prediction or an expectation.
    """
    true_positives: dict[QueryClass, int] = defaultdict(int)
    predicted_count: dict[QueryClass, int] = defaultdict(int)
    expected_count: dict[QueryClass, int] = defaultdict(int)

    for predicted, expected in predictions:
        predicted_count[predicted] += 1
        expected_count[expected] += 1
        if predicted == expected:
            true_positives[predicted] += 1

    all_classes = set(predicted_count) | set(expected_count)
    result: dict[QueryClass, ClassMetrics] = {}
    for query_class in all_classes:
        tp = true_positives[query_class]
        predicted_n = predicted_count[query_class]
        expected_n = expected_count[query_class]
        precision = tp / predicted_n if predicted_n else 0.0
        recall = tp / expected_n if expected_n else 0.0
        result[query_class] = ClassMetrics(
            query_class=query_class, precision=precision, recall=recall, support=expected_n
        )
    return result


def escalation_rate(escalation_counts: Sequence[int]) -> float:
    """Fraction of queries that escalated at least once.

    Args:
        escalation_counts: Number of escalation steps per query (0 = no
            escalation).

    Returns:
        Fraction (``[0, 1]``) of queries with at least one escalation.
    """
    if not escalation_counts:
        return 0.0
    escalated = sum(1 for count in escalation_counts if count > 0)
    return escalated / len(escalation_counts)


def wasted_work_ratio(escalated_cost_ms: float, correct_first_time_cost_ms: float) -> float:
    """Cost of the escalated path ÷ cost of the correct-first-time path (spec §7).

    Args:
        escalated_cost_ms: Total wall-clock cost when the router escalated
            before reaching a sufficient result.
        correct_first_time_cost_ms: Cost the SAME query would have taken
            had the router picked the correct rung first.

    Returns:
        The ratio. ``1.0`` means no waste; values `> 1.0` quantify the
        overhead of misrouting-then-escalating.
    """
    if correct_first_time_cost_ms <= 0:
        return 1.0
    return escalated_cost_ms / correct_first_time_cost_ms


def recall_at_k(retrieved_node_ids: Sequence[str], reference_node_ids: Iterable[str], k: int) -> float:
    """Reference-based node-set recall@k (spec §7) — no LLM judging.

    Args:
        retrieved_node_ids: Node ids returned by a policy, best-first.
        reference_node_ids: The golden set's labelled correct answer set.
        k: How many of `retrieved_node_ids` to consider.

    Returns:
        Fraction of `reference_node_ids` present in the top-`k` of
        `retrieved_node_ids`. ``1.0`` if the reference set is empty.
    """
    reference = set(reference_node_ids)
    if not reference:
        return 1.0
    top_k = set(retrieved_node_ids[:k])
    return len(reference & top_k) / len(reference)


class LatencyPercentiles(BaseModel):
    """p50/p95/p99 latency (spec §7).

    Attributes:
        p50: Median latency, milliseconds.
        p95: 95th percentile latency, milliseconds.
        p99: 99th percentile latency, milliseconds.
        count: Number of samples the percentiles were computed over.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    p50: float
    p95: float
    p99: float
    count: int


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile over already-sorted `sorted_values`."""
    if not sorted_values:
        return 0.0
    index = max(0, min(len(sorted_values) - 1, round(fraction * (len(sorted_values) - 1))))
    return sorted_values[index]


def latency_percentiles(latencies_ms: Sequence[float]) -> LatencyPercentiles:
    """Compute p50/p95/p99 over a sample of latencies.

    Args:
        latencies_ms: Per-query wall-clock latencies, in milliseconds.

    Returns:
        The computed `LatencyPercentiles`.
    """
    ordered = sorted(latencies_ms)
    return LatencyPercentiles(
        p50=_percentile(ordered, 0.50),
        p95=_percentile(ordered, 0.95),
        p99=_percentile(ordered, 0.99),
        count=len(ordered),
    )


def traversal_free_fraction(policies_used: Sequence[str]) -> float:
    """Fraction of traffic answered without any traversal or LLM call (spec §4.4).

    This is the headline number the escalation-ladder hypothesis (spec
    §4.4) is measured against: `DirectSymbolPolicy` is the no-traversal,
    no-LLM fast path (spec §5.1) — every other v1 policy performs at least
    a seed search.

    Args:
        policies_used: The `policy` actually used per query (post any
            escalation), as recorded on each query's
            `RetrievalRoutingDecision.policy`.

    Returns:
        Fraction of queries whose final policy was ``"DirectSymbolPolicy"``.
    """
    if not policies_used:
        return 0.0
    direct = sum(1 for p in policies_used if p == "DirectSymbolPolicy")
    return direct / len(policies_used)


def check_regression(
    baseline: Mapping[QueryClass, float],
    candidate: Mapping[QueryClass, float],
    *,
    tolerance: float = 0.05,
) -> list[QueryClass]:
    """Regression gate: which classes degraded beyond `tolerance` (spec §7).

    "A routing rule change that improves one class must not degrade
    another beyond a set tolerance" — this checks every class
    independently; an improvement elsewhere never offsets a regression.

    Args:
        baseline: ``QueryClass -> metric`` (e.g. recall) from the prior run.
        candidate: ``QueryClass -> metric`` from the run under test.
        tolerance: Maximum allowed drop before a class is flagged.

    Returns:
        The `QueryClass`es whose `candidate` metric dropped by more than
        `tolerance` versus `baseline`. Empty means the gate passes.
    """
    regressed: list[QueryClass] = []
    for query_class, baseline_value in baseline.items():
        candidate_value = candidate.get(query_class, 0.0)
        if baseline_value - candidate_value > tolerance:
            regressed.append(query_class)
    return regressed
