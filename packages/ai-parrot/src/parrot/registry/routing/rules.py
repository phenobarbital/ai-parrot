"""Fast-path rules engine for the store-level router (FEAT-111 Module 4).

Provides a stateless :func:`apply_rules` function that scores candidate stores
based on heuristic keyword/regex rules.  Hardcoded default rules cover the most
common cases; per-agent ``StoreRule`` lists can be merged on top.

Usage::

    from parrot.registry.routing import apply_rules, DEFAULT_STORE_RULES
    from parrot.tools.multistoresearch import StoreType

    scores = apply_rules(
        "what is the relationship between suppliers and warehouses?",
        DEFAULT_STORE_RULES,
        [StoreType.PGVECTOR, StoreType.ARANGO],
        ontology_annotations={"action": "graph_query"},
    )
    # → [StoreScore(store=ARANGO, confidence=1.0, ...), ...]
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from parrot.registry.routing.models import StoreRule, StoreScore
from parrot.tools.multistoresearch import StoreType

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default store rules (applied before any per-agent overrides)
# ---------------------------------------------------------------------------

DEFAULT_STORE_RULES: list[StoreRule] = [
    # --- PgVector (keyword / factual queries) --------------------------------
    StoreRule(pattern="what is", store=StoreType.PGVECTOR, weight=0.7),
    StoreRule(pattern="define", store=StoreType.PGVECTOR, weight=0.7),
    StoreRule(pattern="explain", store=StoreType.PGVECTOR, weight=0.65),
    StoreRule(pattern="tell me about", store=StoreType.PGVECTOR, weight=0.65),
    StoreRule(pattern="how does", store=StoreType.PGVECTOR, weight=0.65),
    StoreRule(pattern="what are", store=StoreType.PGVECTOR, weight=0.65),
    # --- ArangoDB (graph / relationship queries) -----------------------------
    StoreRule(pattern="graph", store=StoreType.ARANGO, weight=0.85),
    StoreRule(pattern="relationship", store=StoreType.ARANGO, weight=0.85),
    StoreRule(pattern="between", store=StoreType.ARANGO, weight=0.80),
    StoreRule(pattern="connect", store=StoreType.ARANGO, weight=0.80),
    StoreRule(pattern="path from", store=StoreType.ARANGO, weight=0.80),
    StoreRule(pattern="traverse", store=StoreType.ARANGO, weight=0.85),
    StoreRule(pattern="linked", store=StoreType.ARANGO, weight=0.75),
    # --- FAISS (semantic similarity queries) ---------------------------------
    StoreRule(pattern="similar to", store=StoreType.FAISS, weight=0.65),
    StoreRule(pattern="like ", store=StoreType.FAISS, weight=0.60),
    StoreRule(pattern="resembling", store=StoreType.FAISS, weight=0.65),
    StoreRule(pattern="nearest", store=StoreType.FAISS, weight=0.65),
]

# Ontology boost applied when annotations signal a specific store preference.
_ONTOLOGY_BOOST = 0.15


def apply_rules(
    query: str,
    rules: list[StoreRule],
    available_stores: list[StoreType],
    ontology_annotations: Optional[dict],
) -> list[StoreScore]:
    """Score *available_stores* for *query* using the provided *rules*.

    Algorithm:
    1. Lowercase the query once.
    2. For each rule, check whether the query matches (substring or regex).
       If the rule's ``store`` is not in *available_stores* the rule is
       silently skipped.
    3. For each store, keep only the **maximum** weight across all matching
       rules (do NOT sum — keeps confidences bounded in [0, 1]).
    4. Apply ontology boosts (if *ontology_annotations* signals a preference).
    5. Sort descending by confidence.

    Args:
        query: Raw user query string.
        rules: ``StoreRule`` list to evaluate.  Typically the built-in
            :data:`DEFAULT_STORE_RULES` plus any per-agent custom rules.
        available_stores: Stores actually configured on the bot.  Rules
            targeting other stores are filtered out.
        ontology_annotations: Output of ``OntologyPreAnnotator.annotate()``.
            Pass ``None`` or ``{}`` when the ontology is not configured.

    Returns:
        Ranked ``list[StoreScore]`` — descending by confidence.
        Empty list when no rules matched and no ontology signal applied.
    """
    available_set = set(available_stores)
    query_lower = query.lower()

    # Accumulate per-store maximum weight from matching rules.
    store_max: dict[StoreType, float] = {}
    store_reason: dict[StoreType, str] = {}

    # Pre-compile regex rules once to avoid repeated compilation in hot loops.
    compiled: list[tuple[StoreRule, Optional[re.Pattern]]] = []
    for rule in rules:
        if rule.store not in available_set:
            continue
        pattern = re.compile(rule.pattern, re.IGNORECASE) if rule.regex else None
        compiled.append((rule, pattern))

    for rule, pattern in compiled:
        matched = False
        if rule.regex and pattern is not None:
            matched = bool(pattern.search(query))
        else:
            matched = rule.pattern.lower() in query_lower

        if matched:
            prev = store_max.get(rule.store, -1.0)
            if rule.weight > prev:
                store_max[rule.store] = rule.weight
                store_reason[rule.store] = f"rule match: '{rule.pattern}'"

    # Apply ontology boosts.
    if ontology_annotations:
        action = ontology_annotations.get("action", "")
        if action == "graph_query" and StoreType.ARANGO in available_set:
            prev = store_max.get(StoreType.ARANGO, 0.0)
            boosted = min(1.0, prev + _ONTOLOGY_BOOST)
            if boosted >= prev:
                store_max[StoreType.ARANGO] = boosted
                store_reason[StoreType.ARANGO] = (
                    store_reason.get(StoreType.ARANGO, "") + " [ontology:graph_query]"
                ).strip()
        if action == "vector_only" and StoreType.PGVECTOR in available_set:
            prev = store_max.get(StoreType.PGVECTOR, 0.0)
            boosted = min(1.0, prev + _ONTOLOGY_BOOST)
            if boosted >= prev:
                store_max[StoreType.PGVECTOR] = boosted
                store_reason[StoreType.PGVECTOR] = (
                    store_reason.get(StoreType.PGVECTOR, "") + " [ontology:vector_only]"
                ).strip()

    if not store_max:
        return []

    scores = [
        StoreScore(store=st, confidence=conf, reason=store_reason.get(st, ""))
        for st, conf in store_max.items()
    ]
    scores.sort(key=lambda s: s.confidence, reverse=True)
    return scores
