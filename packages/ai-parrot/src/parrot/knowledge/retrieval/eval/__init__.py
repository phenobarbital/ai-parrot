"""Evaluation harness for the GraphIndex Retrieval Layer (spec §7).

"Routing decisions are worthless without measurement. Ship the harness
with the feature, not after." Reference-based only — **no LLM-as-judge
anywhere in this package** (spec §7 states the documented position/
length/trial biases that rule it out).
"""

from parrot.knowledge.retrieval.eval.harness import (
    GoldenQuery,
    GoldenSet,
    HeadToHeadReport,
    RoutingEvalReport,
    load_golden_set,
    run_head_to_head,
    run_routing_eval,
)
from parrot.knowledge.retrieval.eval.metrics import (
    ClassMetrics,
    LatencyPercentiles,
    check_regression,
    escalation_rate,
    latency_percentiles,
    precision_recall_per_class,
    recall_at_k,
    traversal_free_fraction,
    wasted_work_ratio,
)

__all__ = [
    "ClassMetrics",
    "GoldenQuery",
    "GoldenSet",
    "HeadToHeadReport",
    "LatencyPercentiles",
    "RoutingEvalReport",
    "check_regression",
    "escalation_rate",
    "latency_percentiles",
    "load_golden_set",
    "precision_recall_per_class",
    "recall_at_k",
    "run_head_to_head",
    "run_routing_eval",
    "traversal_free_fraction",
    "wasted_work_ratio",
]
