"""`SufficiencyCheck` + the sequential escalation driver (spec §4.4).

"Route optimistically, escalate on measured insufficiency" — the
alternative to pessimistic routing (sending every query through
traversal), and where the latency saving in this design actually comes
from.

The ladder: ``DIRECT_SYMBOL -> LOCAL_FACT -> RELATIONAL -> GLOBAL_SUMMARY``.
In the v1 cut only the first two rungs have implemented policies
(`DirectSymbolPolicy`, `VectorSeedPolicy`) — escalation beyond
``LOCAL_FACT`` degrades honestly: the attempt is recorded, the
unimplemented policy is never reported as having run.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from parrot.knowledge.retrieval.classifier import (
    EscalationStep,
    QueryClass,
    RetrievalRoutingDecision,
)
from parrot.knowledge.retrieval.models import (
    ContextBundle,
    RetrievalBudget,
    RetrievalRequest,
)
from parrot.knowledge.retrieval.policies.base import RetrievalPolicyProtocol, Seed
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex

logger = logging.getLogger(__name__)


class SufficiencyTrigger(StrEnum):
    """Which deterministic insufficiency signal fired (spec §4.4)."""

    COVERAGE = "coverage"
    MARGIN = "margin"
    DANGLING = "dangling"


class EscalationMode(StrEnum):
    """How escalation across the ladder is executed (spec §4.4, OQ-4).

    Attributes:
        SEQUENTIAL: Default — escalate one rung at a time, only when the
            previous rung proved insufficient.
        SPECULATIVE: Deferred to v1.1 (T7b) — run the driver in this mode
            and it raises `NotImplementedError`. Defined now so the
            admission contract (`check_speculation_admission`) is decided
            before it lands.
        OFF: Single policy, no escalation — for benchmarking (spec §4.4).
    """

    SEQUENTIAL = "sequential"
    SPECULATIVE = "speculative"
    OFF = "off"


#: The escalation ladder (spec §4.4). Only the first two rungs have
#: implemented policies in the v1 cut (spec §10); `RELATIONAL` and
#: `GLOBAL_SUMMARY` are included so the driver can detect — and honestly
#: report — that it has nowhere further to go.
_LADDER: tuple[QueryClass, ...] = (
    QueryClass.DIRECT_SYMBOL,
    QueryClass.LOCAL_FACT,
    QueryClass.RELATIONAL,
    QueryClass.GLOBAL_SUMMARY,
)

#: Policy kind identifier per rung (spec §4.1), for `EscalationStep.
#: policy_attempted` — independent of whether that policy is implemented.
_POLICY_NAME_BY_RUNG: dict[QueryClass, str] = {
    QueryClass.DIRECT_SYMBOL: "DirectSymbolPolicy",
    QueryClass.LOCAL_FACT: "VectorSeedPolicy",
    QueryClass.RELATIONAL: "PersonalizedPageRankPolicy",
    QueryClass.GLOBAL_SUMMARY: "AncestrySummaryPolicy",
}

#: Call-like tokens: an identifier immediately followed by ``(`` — the
#: `dangling` trigger's target shape (spec §4.4: "call target missing").
_CALL_TOKEN_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def _next_rung(query_class: QueryClass) -> QueryClass | None:
    """Return the next rung up the ladder from `query_class`, or ``None``."""
    if query_class not in _LADDER:
        return None
    index = _LADDER.index(query_class)
    if index + 1 >= len(_LADDER):
        return None
    return _LADDER[index + 1]


class SufficiencyCheck(BaseModel):
    """The three deterministic insufficiency triggers (spec §4.4).

    A result is `insufficient` when any trigger fires — evaluated in
    ``coverage -> margin -> dangling`` order (the order in which the spec
    presents them); the first one found is reported.

    Attributes:
        min_units: `coverage` fires when fewer than this many units
            survived pruning.
        margin_threshold: `margin` fires when the ratio of the top seed's
            score to the lowest-ranked returned seed's score is below this
            threshold — i.e. the distribution is too flat for anything to
            have "stood out". A ratio of ``1.0`` means all scores are
            identical; larger ratios mean a clearer winner.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_units: int = 3
    margin_threshold: float = 1.2

    def evaluate(
        self,
        bundle: ContextBundle,
        seeds: tuple[Seed, ...],
        symbols: DerivedSymbolIndex,
    ) -> SufficiencyTrigger | None:
        """Evaluate all three triggers against one bundle.

        Args:
            bundle: The `ContextBundle` produced by a policy's `assemble`.
            seeds: The `Seed`s that policy's `seed` stage produced.
            symbols: The `DerivedSymbolIndex` used to resolve call targets
                for the `dangling` trigger.

        Returns:
            The first `SufficiencyTrigger` that fired, or ``None`` if the
            result is sufficient.
        """
        if self._check_coverage(bundle):
            return SufficiencyTrigger.COVERAGE
        if self._check_margin(seeds):
            return SufficiencyTrigger.MARGIN
        if self._check_dangling(bundle, symbols):
            return SufficiencyTrigger.DANGLING
        return None

    def _check_coverage(self, bundle: ContextBundle) -> bool:
        """``True`` iff fewer than `min_units` units survived pruning."""
        return len(bundle.units) < self.min_units

    def _check_margin(self, seeds: tuple[Seed, ...]) -> bool:
        """``True`` iff the seed score distribution is too flat.

        With fewer than two seeds there is no distribution to be flat —
        not a margin failure.
        """
        if len(seeds) < 2:
            return False
        scores = sorted((s.score for s in seeds), reverse=True)
        top1, bottom = scores[0], scores[-1]
        if top1 <= 0:
            return True
        ratio = top1 / bottom if bottom > 0 else float("inf")
        return ratio < self.margin_threshold

    def _check_dangling(self, bundle: ContextBundle, symbols: DerivedSymbolIndex) -> bool:
        """``True`` iff a unit calls a symbol resolvable but absent from `bundle`.

        A structural signal only a code graph can give (spec §4.4): the
        call target is a real, resolvable symbol — just not one the
        policy chose to include.
        """
        present_qualnames = {unit.evidence.node.qualname for unit in bundle.units}
        for unit in bundle.units:
            for call_name in _CALL_TOKEN_RE.findall(unit.text):
                for candidate in symbols.resolve(call_name):
                    if candidate.qualname not in present_qualnames:
                        return True
        return False


#: Shared, frozen default — constructed once at module load, not per call
#: (ruff B008: no function calls in argument defaults).
_DEFAULT_SUFFICIENCY_CHECK = SufficiencyCheck()


def check_speculation_admission(*, max_llm_calls: int, pin_count: int) -> None:
    """Enforce `SPECULATIVE` mode's admission rules (spec §4.4, RQ-3).

    Written now so T7b (speculation) inherits a decided contract rather
    than deciding it under deadline pressure later.

    Args:
        max_llm_calls: The request budget's `max_llm_calls`.
        pin_count: ``len(workspace.pins)``.

    Raises:
        ValueError: If `max_llm_calls` is not ``0``, or `pin_count` is not
            exactly ``1`` (RQ-3: the shared-seed guarantee speculation
            relies on is per-store, and stores are not shared across
            pins).
    """
    if max_llm_calls > 0:
        raise ValueError(
            "Speculative escalation requires budget.max_llm_calls == 0 "
            f"(got {max_llm_calls})"
        )
    if pin_count != 1:
        raise ValueError(
            f"Speculative escalation requires exactly one workspace pin (RQ-3); "
            f"got {pin_count}"
        )


async def _run_policy_stages(
    policy: RetrievalPolicyProtocol,
    req: RetrievalRequest,
    graph: Any,
    budget: RetrievalBudget,
) -> tuple[tuple[Seed, ...], ContextBundle]:
    """Run one rung's full seed→expand→prune→assemble pipeline.

    Factored out so `run_escalation_ladder` can wrap the WHOLE pipeline in
    a single `asyncio.wait_for` — enforcing `budget.deadline_ms` as a hard
    ceiling at the orchestration level (INV-5), rather than trusting each
    stage's own self-reported `truncated` flag, which only tracks elapsed
    time within that one stage.

    Args:
        policy: The policy to run.
        req: The retrieval request.
        graph: Passed through to `seed`/`expand`.
        budget: This rung's `RetrievalBudget`.

    Returns:
        ``(seeds, bundle)`` from the completed pipeline.
    """
    seeds = await policy.seed(req, graph)
    subgraph = await policy.expand(seeds, graph, budget)
    pruned = await policy.prune(subgraph, budget)
    bundle = await policy.assemble(pruned, budget)
    return seeds, bundle


async def run_escalation_ladder(
    *,
    start_class: QueryClass,
    decision: RetrievalRoutingDecision,
    policies: Mapping[QueryClass, RetrievalPolicyProtocol],
    req: RetrievalRequest,
    budget: RetrievalBudget,
    symbols: DerivedSymbolIndex,
    graph: Any = None,
    mode: EscalationMode = EscalationMode.SEQUENTIAL,
    sufficiency: SufficiencyCheck = _DEFAULT_SUFFICIENCY_CHECK,
) -> tuple[ContextBundle | None, RetrievalRoutingDecision]:
    """Run `start_class`'s policy, escalating one rung at a time on insufficiency.

    Budget is decremented across steps: each rung's `RetrievalBudget` gets
    only the deadline remaining after prior rungs, and the driver stops
    (flagging `truncated=True`) rather than let N escalations collectively
    exceed the original `budget.deadline_ms` (INV-5).

    Args:
        start_class: The `QueryClass` `QueryClassifier.classify()` routed
            to — the ladder's starting rung.
        decision: The `RetrievalRoutingDecision` to attach escalations to.
        policies: ``QueryClass -> policy`` for every rung that HAS an
            implemented policy in this deployment (v1: `DIRECT_SYMBOL`,
            `LOCAL_FACT` only). Missing entries mean "not implemented" —
            handled honestly, never silently skipped-as-success.
        req: The retrieval request.
        budget: The request's original `RetrievalBudget`.
        symbols: The `DerivedSymbolIndex`, for the `dangling` trigger.
        graph: Passed through to each policy's `seed`/`expand` stages.
        mode: `EscalationMode` — `SPECULATIVE` raises immediately.
        sufficiency: The `SufficiencyCheck` to evaluate after each rung.

    Returns:
        ``(bundle, decision)`` — `bundle` is ``None`` only if `start_class`
        itself has no implemented policy. `decision.escalations` records
        every attempted step.

    Raises:
        NotImplementedError: If `mode` is `EscalationMode.SPECULATIVE` —
            deferred to v1.1 (T7b, spec §10).
    """
    if mode == EscalationMode.SPECULATIVE:
        raise NotImplementedError(
            "EscalationMode.SPECULATIVE is deferred to v1.1 (T7b) — not implemented"
        )

    remaining_ms = float(budget.deadline_ms)
    escalations: list[EscalationStep] = []
    current_class = start_class
    bundle: ContextBundle | None = None

    while True:
        policy = policies.get(current_class)
        if policy is None:
            logger.warning(
                "run_escalation_ladder: no implemented policy for %s — stopping", current_class
            )
            break

        step_budget = RetrievalBudget(
            deadline_ms=max(int(remaining_ms), 0),
            max_tokens=budget.max_tokens,
            max_llm_calls=budget.max_llm_calls,
            max_expansion_nodes=budget.max_expansion_nodes,
            allow_stale=budget.allow_stale,
        )
        if step_budget.deadline_ms <= 0:
            if bundle is not None:
                bundle = bundle.model_copy(update={"truncated": True})
            break

        step_start = time.monotonic()
        try:
            # Hard-enforce INV-5 at the orchestration level rather than
            # trusting each stage's self-reported `truncated` (code
            # review: a stage's own elapsed-time check resets per stage,
            # so a slow stage could otherwise overrun the rung's actual
            # remaining budget with no way to be interrupted).
            seeds, bundle = await asyncio.wait_for(
                _run_policy_stages(policy, req, graph, step_budget),
                timeout=step_budget.deadline_ms / 1000,
            )
        except TimeoutError:
            elapsed_ms = (time.monotonic() - step_start) * 1000
            remaining_ms -= elapsed_ms
            logger.warning(
                "run_escalation_ladder: %s exceeded its %d ms budget — truncating",
                current_class,
                step_budget.deadline_ms,
            )
            if bundle is not None:
                bundle = bundle.model_copy(update={"truncated": True})
            else:
                # Not even the first rung completed — INV-5 still requires
                # a (flagged) result rather than None, per this function's
                # own contract ("bundle is None only if start_class itself
                # has no implemented policy").
                bundle = ContextBundle(
                    units=(),
                    decision=None,
                    truncated=True,
                    token_total=0,
                    elapsed_ms=elapsed_ms,
                )
            break
        assert bundle is not None  # narrows for mypy: the `except` branch above always `break`s
        elapsed_ms = (time.monotonic() - step_start) * 1000
        remaining_ms -= elapsed_ms

        if mode == EscalationMode.OFF:
            break

        trigger = sufficiency.evaluate(bundle, seeds, symbols)
        if trigger is None:
            break

        next_class = _next_rung(current_class)
        if next_class is None:
            escalations.append(
                EscalationStep(
                    from_class=current_class,
                    to_class=current_class,
                    trigger=trigger.value,
                    elapsed_ms=elapsed_ms,
                    policy_attempted=_POLICY_NAME_BY_RUNG.get(current_class, current_class.value),
                    used=True,
                )
            )
            break

        next_policy_name = _POLICY_NAME_BY_RUNG.get(next_class, next_class.value)

        if remaining_ms <= 0 or next_class not in policies:
            bundle = bundle.model_copy(update={"truncated": True})
            escalations.append(
                EscalationStep(
                    from_class=current_class,
                    to_class=next_class,
                    trigger=trigger.value,
                    elapsed_ms=elapsed_ms,
                    policy_attempted=next_policy_name,
                    used=False,
                )
            )
            break

        escalations.append(
            EscalationStep(
                from_class=current_class,
                to_class=next_class,
                trigger=trigger.value,
                elapsed_ms=elapsed_ms,
                policy_attempted=next_policy_name,
                used=True,
            )
        )
        current_class = next_class

    final_decision = decision.model_copy(update={"escalations": tuple(escalations)})
    return bundle, final_decision
