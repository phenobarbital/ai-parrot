"""`QueryClassifier` — the decision list that routes a query to a policy.

Spec §4.3. Deliberately a decision list, not a model: "auditable, zero
warm-up, zero drift". INV-3 makes `classify()` a pure function of
``(query_text, GraphStats, RetrievalBudget)`` — no I/O, no LLM call, no
clock, same inputs → same decision, always replayable offline.

**Naming (spec §5.0):** this feature's routing-decision model is
`RetrievalRoutingDecision`, never `RoutingDecision` — that name belongs to
`parrot/bots/mixins/intent_router.py` (LLM intent routing, an unrelated
concern). Do not import or extend it here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from parrot.knowledge.retrieval.features import QueryFeatures, extract_features
from parrot.knowledge.retrieval.models import RetrievalBudget
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex

logger = logging.getLogger(__name__)


class QueryClass(StrEnum):
    """The query taxonomy a `QueryClassifier` routes into (spec §4.1)."""

    DIRECT_SYMBOL = "direct_symbol"
    LOCAL_FACT = "local_fact"
    RELATIONAL = "relational"
    RATIONALE = "rationale"
    GLOBAL_SUMMARY = "global_summary"
    COMPARATIVE = "comparative"
    UNKNOWN = "unknown"


class GraphStats(BaseModel):
    """Minimal placeholder graph statistics (INV-3's `classify()` input).

    None of the v1 decision rules (R1-R7) actually key off graph-wide
    statistics — they are pure functions of `QueryFeatures` — but INV-3
    names `GraphStats` as part of `classify()`'s input signature, so the
    type exists here rather than being invented ad hoc later. Deliberately
    minimal: do not wire up `graphindex/analytics.py` (heavier than the
    classifier's sub-millisecond latency budget allows) — that is future
    work, not this task's scope.

    Attributes:
        node_count: Total resident node count, if known.
        edge_count: Total resident edge count, if known.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_count: int = 0
    edge_count: int = 0


class EscalationStep(BaseModel):
    """One step of the escalation ladder (spec §4.4).

    Populated by TASK-2282's sequential escalation driver
    (`parrot.knowledge.retrieval.escalation`) and appended to
    `RetrievalRoutingDecision.escalations` so wasted-work ratio (spec §7)
    stays measurable — every attempted escalation is recorded, including
    ones that could not run because the next rung's policy is not yet
    implemented in the v1 cut.

    Attributes:
        from_class: The `QueryClass` escalated away from.
        to_class: The `QueryClass` escalated to.
        trigger: Which `SufficiencyCheck` fired (``"coverage"``,
            ``"margin"``, ``"dangling"``).
        elapsed_ms: Cost of the step that was escalated away from.
        policy_attempted: Kind identifier of the policy the ladder tried
            to escalate to (e.g. ``"PersonalizedPageRankPolicy"``) —
            recorded even when that policy is not in the v1 cut and could
            not actually run.
        used: Whether `policy_attempted` actually ran and its result was
            used. ``False`` when the rung's policy is unimplemented, or
            when the escalation was attempted but the deadline was hit
            first — the attempt is still recorded, never silently dropped.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    from_class: QueryClass
    to_class: QueryClass
    trigger: str
    elapsed_ms: float
    policy_attempted: str = ""
    used: bool = False


class RetrievalRoutingDecision(BaseModel):
    """The full routing trace for one request (spec §4.3, §8).

    Fully serializable (`model_dump_json`/`model_validate_json`) so a
    production trace can be replayed offline against a modified decision
    list with no retrieval re-execution (spec §8).

    Attributes:
        query_class: The `QueryClass` this query was routed to. When
            `policy_override` was used, this reflects `QueryClass.UNKNOWN`
            since classification was bypassed entirely.
        policy: Kind identifier of the policy actually selected to run
            (e.g. ``"DirectSymbolPolicy"``). A v1-cut identifier — no
            `RetrievalPolicy` discriminated union exists yet (T5 onward).
        intended_policy: Set when `query_class`'s spec-table default policy
            (spec §4.1) is not yet implemented in the v1 cut and a
            substitution to `policy` occurred. ``None`` when `policy` IS
            the intended default — the substitution is never silent.
        matched_rule: Which rule matched (``"R1"``..``"R7"``), or
            ``"OVERRIDE"`` when `policy_override` bypassed classification.
        features: The `QueryFeatures` classification was computed from.
        escalations: Steps taken by the escalation ladder (spec §4.4).
            Always empty from `classify()` itself — TASK-2282 appends to
            this during execution.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    query_class: QueryClass
    policy: str
    intended_policy: str | None = None
    matched_rule: str
    features: QueryFeatures
    escalations: tuple[EscalationStep, ...] = ()


#: Ordered `(rule_id, predicate, QueryClass)` — first-match-wins (spec
#: §4.3). Kept as a table, not an if/elif chain, so it reads like the spec
#: and "every rule is reachable" is trivial to test.
_RULES: tuple[tuple[str, Callable[[QueryFeatures], bool], QueryClass], ...] = (
    (
        "R1",
        lambda f: f.anchor_count == 1 and f.token_count <= 6 and not f.has_relational_verb,
        QueryClass.DIRECT_SYMBOL,
    ),
    ("R2", lambda f: f.has_causal_marker, QueryClass.RATIONALE),
    ("R3", lambda f: f.anchor_count >= 2, QueryClass.COMPARATIVE),
    (
        "R4",
        lambda f: f.has_relational_verb and f.anchor_count >= 1,
        QueryClass.RELATIONAL,
    ),
    (
        "R5",
        lambda f: f.has_aggregation_marker and not f.has_code_literal,
        QueryClass.GLOBAL_SUMMARY,
    ),
    ("R6", lambda f: f.anchor_count >= 1 or f.has_code_literal, QueryClass.LOCAL_FACT),
    ("R7", lambda _f: True, QueryClass.UNKNOWN),
)

#: Default policy per `QueryClass` (spec §4.1 table).
_DEFAULT_POLICY_BY_CLASS: dict[QueryClass, str] = {
    QueryClass.DIRECT_SYMBOL: "DirectSymbolPolicy",
    QueryClass.LOCAL_FACT: "VectorSeedPolicy",
    QueryClass.RELATIONAL: "PersonalizedPageRankPolicy",
    QueryClass.RATIONALE: "RationalePolicy",
    QueryClass.GLOBAL_SUMMARY: "AncestrySummaryPolicy",
    QueryClass.COMPARATIVE: "SteinerTreePolicy",
    QueryClass.UNKNOWN: "VectorSeedPolicy",
}

#: Policies actually implemented in the v1 cut (spec §10 revised v1 cut:
#: only T5 `DirectSymbolPolicy` and T6 `VectorSeedPolicy`). Any class whose
#: default policy is NOT in this set falls back to `VectorSeedPolicy`, with
#: the substitution recorded on `RetrievalRoutingDecision.intended_policy`.
_V1_CUT_POLICIES: frozenset[str] = frozenset({"DirectSymbolPolicy", "VectorSeedPolicy"})


def _select_policy(query_class: QueryClass) -> tuple[str, str | None]:
    """Return ``(policy, intended_policy)`` for `query_class`.

    Args:
        query_class: The classified `QueryClass`.

    Returns:
        ``(policy, None)`` when the spec-table default is implemented in
        the v1 cut, or ``(substitute, intended)`` when it is not — the
        substitution is always recorded, never silent (spec §10).
    """
    intended = _DEFAULT_POLICY_BY_CLASS[query_class]
    if intended in _V1_CUT_POLICIES:
        return intended, None
    return "VectorSeedPolicy", intended


class QueryClassifier:
    """Pure, deterministic query router (spec §4).

    Design principle: **the classifier must never be the thing that costs
    latency.** `classify()` is a pure function over cheap `QueryFeatures` —
    no I/O, no LLM call, no clock (INV-3).
    """

    def __init__(self, symbols: DerivedSymbolIndex, *, shadow_mode: bool = False) -> None:
        """Construct a classifier bound to one `DerivedSymbolIndex`.

        Args:
            symbols: The in-process symbol index `extract_features` will
                resolve code-literal tokens against.
            shadow_mode: Default shadow-mode setting (spec §4.5) — classify
                and log, but the decision is not meant to be acted upon by
                the caller. Can be overridden per-call.
        """
        self.symbols = symbols
        self.shadow_mode = shadow_mode
        self.logger = logging.getLogger(__name__)

    def classify(
        self,
        query: str,
        stats: GraphStats | None = None,
        budget: RetrievalBudget | None = None,
        *,
        policy_override: str | None = None,
        shadow_mode: bool | None = None,
    ) -> RetrievalRoutingDecision:
        """Classify `query` into a `RetrievalRoutingDecision`.

        Pure function of ``(query, stats, budget)`` plus the classifier's
        bound `symbols` index (INV-3): no I/O, no LLM call, no clock. Same
        inputs always produce a byte-identical decision.

        Args:
            query: The natural-language query text.
            stats: Graph-wide statistics (currently unused by any v1 rule
                — accepted for INV-3 signature completeness).
            budget: The request's `RetrievalBudget` (currently unused by
                any v1 rule — accepted for INV-3 signature completeness).
            policy_override: Escape hatch (spec §4.5) — bypasses rule
                evaluation entirely, forcing `policy`. Logged, and sets
                `matched_rule="OVERRIDE"`.
            shadow_mode: Per-call override of the constructor's
                `shadow_mode` default. When true, the decision is logged
                as shadow-mode (for offline calibration) but is otherwise
                identical — `classify()` never "acts" on a decision itself,
                so shadow mode changes only the log record, not the return
                value.

        Returns:
            The `RetrievalRoutingDecision` — `matched_rule` names exactly
            which rule fired (or ``"OVERRIDE"``).
        """
        del stats, budget  # unused by v1 rules; kept for INV-3 signature completeness
        effective_shadow = self.shadow_mode if shadow_mode is None else shadow_mode
        features = extract_features(query, self.symbols)

        if policy_override is not None:
            decision = RetrievalRoutingDecision(
                query_class=QueryClass.UNKNOWN,
                policy=policy_override,
                matched_rule="OVERRIDE",
                features=features,
            )
            self.logger.info(
                "QueryClassifier: policy_override=%r bypasses classification (matched_rule=OVERRIDE)",
                policy_override,
            )
            return decision

        for rule_id, predicate, query_class in _RULES:
            if not predicate(features):
                continue
            policy, intended_policy = _select_policy(query_class)
            decision = RetrievalRoutingDecision(
                query_class=query_class,
                policy=policy,
                intended_policy=intended_policy,
                matched_rule=rule_id,
                features=features,
            )
            if effective_shadow:
                self.logger.info(
                    "QueryClassifier[shadow_mode]: query_class=%s matched_rule=%s "
                    "policy=%s (not acted upon by classify() itself)",
                    query_class,
                    rule_id,
                    policy,
                )
            return decision

        # R7 (`lambda _f: True`) always matches — this is unreachable.
        raise AssertionError("QueryClassifier: no rule matched — R7 should be a catch-all")
