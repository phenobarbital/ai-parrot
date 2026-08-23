"""The evaluation harness itself (spec §7): golden set + routing eval + head-to-head.

A single command produces the whole report; the golden set is loadable
independently of the harness — the labelled query set is the durable
asset here and will outlive any particular implementation of the
retriever it measures.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from parrot.knowledge.retrieval.classifier import QueryClass, QueryClassifier
from parrot.knowledge.retrieval.eval.metrics import (
    ClassMetrics,
    LatencyPercentiles,
    latency_percentiles,
    precision_recall_per_class,
    recall_at_k,
    traversal_free_fraction,
)

logger = logging.getLogger(__name__)

#: Default location of the committed golden set (spec §7).
_DEFAULT_GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.json"

#: Below this recall-fraction margin, a head-to-head win is declared
#: inconclusive rather than a win (spec §7: "Treat a narrow margin as
#: inconclusive rather than a win").
_INCONCLUSIVE_MARGIN = 0.05


class GoldenQuery(BaseModel):
    """One hand-authored, labelled golden-set query (spec §7).

    Attributes:
        id: Stable query identifier (e.g. ``"q0001"``).
        query: The natural-language query text.
        language: ``"es"`` or ``"en"``.
        expected_class: The `QueryClass` this query should be routed to.
        expected_rule: Which decision-list rule (``"R1"``..``"R7"``)
            should match.
        reference_nodes: The labelled ground-truth answer set — node
            identifiers (qualnames, in this golden set) a correct
            retrieval should surface.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    query: str
    language: str
    expected_class: QueryClass
    expected_rule: str
    reference_nodes: tuple[str, ...] = ()


class GoldenSet(BaseModel):
    """The versioned, committed golden set (spec §7).

    Attributes:
        version: Bumped whenever the query set changes, so a report
            states which version it was measured against.
        created: ISO date the set was authored/last revised.
        description: Free-form provenance note.
        queries: The labelled queries.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    created: str
    description: str
    queries: tuple[GoldenQuery, ...]


def load_golden_set(path: Path | None = None) -> GoldenSet:
    """Load the committed golden set from disk.

    Args:
        path: Path to the golden set JSON file. Defaults to the file
            committed alongside this module (`golden_set.json`).

    Returns:
        The parsed, validated `GoldenSet`.
    """
    target = path or _DEFAULT_GOLDEN_SET_PATH
    with open(target, encoding="utf-8") as fh:
        raw = json.load(fh)
    return GoldenSet.model_validate(raw)


class RoutingEvalReport(BaseModel):
    """Routing-quality metrics over one golden-set run (spec §7).

    Attributes:
        golden_set_version: Which `GoldenSet.version` this measures.
        per_class: Precision/recall/support per `QueryClass`.
        escalation_rate: Fraction of queries that escalated at least once.
        traversal_free_fraction: Fraction answered by `DirectSymbolPolicy`
            alone — the §4.4 headline number.
        latency: p50/p95/p99 over per-query `classify()` wall time.
        rule_hit_counts: How many golden-set queries matched each rule —
            used to confirm every rule R1-R7 is actually exercised.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    golden_set_version: str
    per_class: dict[QueryClass, ClassMetrics]
    escalation_rate: float
    traversal_free_fraction: float
    latency: LatencyPercentiles
    rule_hit_counts: dict[str, int]


def run_routing_eval(classifier: QueryClassifier, golden_set: GoldenSet) -> RoutingEvalReport:
    """Run every golden-set query through `classifier` and score routing quality.

    `classify()` itself never escalates or executes a policy (INV-3) —
    this measures classification quality only. Escalation execution and
    per-query latency of the full retrieval pipeline is a separate,
    heavier measurement left to a caller that wires up real policies.

    Args:
        classifier: The `QueryClassifier` under test.
        golden_set: The labelled golden set to run.

    Returns:
        The computed `RoutingEvalReport`.
    """
    predictions: list[tuple[QueryClass, QueryClass]] = []
    latencies_ms: list[float] = []
    policies_used: list[str] = []
    rule_hit_counts: dict[str, int] = {}

    for entry in golden_set.queries:
        start = time.monotonic()
        decision = classifier.classify(entry.query)
        elapsed_ms = (time.monotonic() - start) * 1000

        predictions.append((decision.query_class, entry.expected_class))
        latencies_ms.append(elapsed_ms)
        policies_used.append(decision.policy)
        rule_hit_counts[decision.matched_rule] = rule_hit_counts.get(decision.matched_rule, 0) + 1

    return RoutingEvalReport(
        golden_set_version=golden_set.version,
        per_class=precision_recall_per_class(predictions),
        escalation_rate=0.0,  # classify() alone never escalates (INV-3)
        traversal_free_fraction=traversal_free_fraction(policies_used),
        latency=latency_percentiles(latencies_ms),
        rule_hit_counts=rule_hit_counts,
    )


class HeadToHeadReport(BaseModel):
    """FEAT-435 vs FEAT-217's `GraphExpandedRetriever`, same golden set (spec §5.0, OQ-8).

    Attributes:
        golden_set_version: Which `GoldenSet.version` this measures.
        feat_435_recall_at_k: Mean recall@k for this layer.
        feat_217_recall_at_k: Mean recall@k for `GraphExpandedRetriever`.
        feat_435_latency: p50/p95/p99 for this layer.
        feat_217_latency: p50/p95/p99 for `GraphExpandedRetriever`.
        k: The `k` recall@k was computed at.
        verdict: ``"feat_435_wins"``, ``"feat_217_wins"``, or
            ``"inconclusive"`` — a margin below `_INCONCLUSIVE_MARGIN` is
            ALWAYS inconclusive, never declared a win (spec §7).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    golden_set_version: str
    feat_435_recall_at_k: float
    feat_217_recall_at_k: float
    feat_435_latency: LatencyPercentiles
    feat_217_latency: LatencyPercentiles
    k: int
    verdict: str


async def run_head_to_head(
    golden_set: GoldenSet,
    *,
    feat_435_retrieve: Callable[[str], Awaitable[Sequence[str]]],
    feat_217_retrieve: Callable[[str], Awaitable[Sequence[str]]],
    k: int = 10,
) -> HeadToHeadReport:
    """Run the same golden set through both retrievers; report both, fairly.

    Same pinned workspace, same `k`, same golden set, both retrievers
    cold — the caller is responsible for constructing `feat_435_retrieve`/
    `feat_217_retrieve` so that invariant holds (spec §5.0: "Be scrupulous
    about the head-to-head being fair").

    Both callables must return ranked node identifiers in the SAME id
    space as `GoldenQuery.reference_nodes` (this golden set uses stable
    qualnames, not raw L0 `node_id`s, since those are pipeline-specific
    and not stable across re-index runs) — resolving `GraphExpandedRetriever`'s
    raw `node_id`s to that space is the caller's responsibility.

    Args:
        golden_set: The labelled golden set to run through both.
        feat_435_retrieve: Async ``query -> ranked ids`` for this layer.
        feat_217_retrieve: Async ``query -> ranked ids`` for
            `GraphExpandedRetriever` (FEAT-217, read-only — spec §5.0).
        k: recall@k's ``k``.

    Returns:
        The `HeadToHeadReport`, with a `verdict` that is `"inconclusive"`
        whenever the margin is narrow — never asserted as a win on a
        narrow margin (spec §7).
    """
    feat_435_recalls: list[float] = []
    feat_217_recalls: list[float] = []
    feat_435_latencies: list[float] = []
    feat_217_latencies: list[float] = []

    for entry in golden_set.queries:
        if not entry.reference_nodes:
            continue

        start = time.monotonic()
        feat_435_ids = await feat_435_retrieve(entry.query)
        feat_435_latencies.append((time.monotonic() - start) * 1000)
        feat_435_recalls.append(recall_at_k(list(feat_435_ids), entry.reference_nodes, k))

        start = time.monotonic()
        feat_217_ids = await feat_217_retrieve(entry.query)
        feat_217_latencies.append((time.monotonic() - start) * 1000)
        feat_217_recalls.append(recall_at_k(list(feat_217_ids), entry.reference_nodes, k))

    feat_435_mean = sum(feat_435_recalls) / len(feat_435_recalls) if feat_435_recalls else 0.0
    feat_217_mean = sum(feat_217_recalls) / len(feat_217_recalls) if feat_217_recalls else 0.0

    margin = feat_435_mean - feat_217_mean
    if abs(margin) < _INCONCLUSIVE_MARGIN:
        verdict = "inconclusive"
    elif margin > 0:
        verdict = "feat_435_wins"
    else:
        verdict = "feat_217_wins"

    return HeadToHeadReport(
        golden_set_version=golden_set.version,
        feat_435_recall_at_k=feat_435_mean,
        feat_217_recall_at_k=feat_217_mean,
        feat_435_latency=latency_percentiles(feat_435_latencies),
        feat_217_latency=latency_percentiles(feat_217_latencies),
        k=k,
        verdict=verdict,
    )
