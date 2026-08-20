"""Tests for TASK-2282: `SufficiencyCheck` + sequential escalation driver.

Spec: sdd/specs/graphindex-retriever.spec.md §4.4.
"""

import asyncio

import pytest
from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode
from parrot.knowledge.retrieval.classifier import QueryClass, RetrievalRoutingDecision
from parrot.knowledge.retrieval.escalation import (
    EscalationMode,
    SufficiencyCheck,
    SufficiencyTrigger,
    check_speculation_admission,
    run_escalation_ladder,
)
from parrot.knowledge.retrieval.features import QueryFeatures
from parrot.knowledge.retrieval.lexicon import Interrogative
from parrot.knowledge.retrieval.models import (
    ContextBundle,
    ContextUnit,
    Evidence,
    EvidenceOrigin,
    NodeRef,
    RetrievalBudget,
    RetrievalRequest,
)
from parrot.knowledge.retrieval.policies.base import Seed
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex


def _node_ref(qualname: str) -> NodeRef:
    return NodeRef(
        repo="ai-parrot",
        rev="a1b2c3d",
        path="mod.py",
        kind=NodeKind.SYMBOL,
        symbol_type="function",
        qualname=qualname,
    )


def _unit(qualname: str, text: str) -> ContextUnit:
    return ContextUnit(
        text=text,
        evidence=Evidence(
            node=_node_ref(qualname),
            digest="deadbeef",
            digest_scope="span",
            line_span=(1, 2),
            origin=EvidenceOrigin.L0_SOURCE,
            score=1.0,
        ),
        token_estimate=len(text.split()),
    )


def _bundle(units: tuple[ContextUnit, ...], *, truncated: bool = False) -> ContextBundle:
    return ContextBundle(
        units=units,
        decision=None,
        truncated=truncated,
        token_total=sum(u.token_estimate for u in units),
        elapsed_ms=1.0,
    )


def _symbols_with(qualname: str) -> DerivedSymbolIndex:
    node = UniversalNode(
        node_id=f"mod::{qualname}",
        kind=NodeKind.SYMBOL,
        title=qualname,
        source_uri="mod.py",
        domain_tags={"symbol_type": "function"},
    )
    return DerivedSymbolIndex.build([node], repo="ai-parrot", rev="a1b2c3d")


# --- SufficiencyCheck: isolated trigger tests -------------------------------


def test_coverage_trigger_in_isolation() -> None:
    check = SufficiencyCheck(min_units=3)
    bundle = _bundle((_unit("foo", "def foo(): pass"),))
    seeds = (Seed(node=_node_ref("foo"), score=1.0),)
    assert check.evaluate(bundle, seeds, _symbols_with("foo")) == SufficiencyTrigger.COVERAGE


def test_coverage_satisfied_no_trigger() -> None:
    check = SufficiencyCheck(min_units=1)
    bundle = _bundle((_unit("foo", "def foo(): pass"),))
    seeds = (Seed(node=_node_ref("foo"), score=1.0),)
    assert check.evaluate(bundle, seeds, _symbols_with("foo")) is None


def test_margin_trigger_flat_distribution() -> None:
    check = SufficiencyCheck(min_units=1, margin_threshold=1.2)
    bundle = _bundle((_unit("foo", "def foo(): pass"), _unit("bar", "def bar(): pass")))
    seeds = (
        Seed(node=_node_ref("foo"), score=0.50),
        Seed(node=_node_ref("bar"), score=0.49),
    )
    assert check.evaluate(bundle, seeds, _symbols_with("foo")) == SufficiencyTrigger.MARGIN


def test_margin_not_triggered_when_decisive() -> None:
    check = SufficiencyCheck(min_units=1, margin_threshold=1.2)
    bundle = _bundle((_unit("foo", "def foo(): pass"), _unit("bar", "def bar(): pass")))
    seeds = (
        Seed(node=_node_ref("foo"), score=1.0),
        Seed(node=_node_ref("bar"), score=0.1),
    )
    assert check.evaluate(bundle, seeds, _symbols_with("foo")) is None


def test_margin_single_seed_never_flat() -> None:
    check = SufficiencyCheck(min_units=1)
    bundle = _bundle((_unit("foo", "def foo(): pass"),))
    seeds = (Seed(node=_node_ref("foo"), score=0.01),)
    assert check.evaluate(bundle, seeds, _symbols_with("foo")) is None


def test_dangling_trigger_uses_symbol_index() -> None:
    check = SufficiencyCheck(min_units=1)
    # "foo" calls "helper()", which resolves in the symbol index but is
    # NOT among the bundle's own units.
    bundle = _bundle((_unit("foo", "def foo(): return helper()"),))
    seeds = (Seed(node=_node_ref("foo"), score=1.0),)
    symbols = _symbols_with("helper")
    assert check.evaluate(bundle, seeds, symbols) == SufficiencyTrigger.DANGLING


def test_dangling_not_triggered_when_target_present() -> None:
    check = SufficiencyCheck(min_units=1)
    bundle = _bundle(
        (
            _unit("foo", "def foo(): return helper()"),
            _unit("helper", "def helper(): return 1"),
        )
    )
    seeds = (Seed(node=_node_ref("foo"), score=1.0), Seed(node=_node_ref("helper"), score=0.1))
    symbols = _symbols_with("helper")
    assert check.evaluate(bundle, seeds, symbols) is None


# --- Speculation admission --------------------------------------------------


def test_speculation_admission_rejects_llm_calls_and_multipin() -> None:
    with pytest.raises(ValueError, match="max_llm_calls"):
        check_speculation_admission(max_llm_calls=1, pin_count=1)
    with pytest.raises(ValueError, match="pin"):
        check_speculation_admission(max_llm_calls=0, pin_count=2)
    check_speculation_admission(max_llm_calls=0, pin_count=1)  # does not raise


def test_speculative_mode_raises_not_implemented() -> None:
    decision = RetrievalRoutingDecision(
        query_class=QueryClass.LOCAL_FACT,
        policy="VectorSeedPolicy",
        matched_rule="R6",
        features=_features(),
    )
    with pytest.raises(NotImplementedError):
        asyncio.run(
            run_escalation_ladder(
                start_class=QueryClass.LOCAL_FACT,
                decision=decision,
                policies={},
                req=RetrievalRequest(query="q", workspace=None),
                budget=RetrievalBudget(),
                symbols=_symbols_with("foo"),
                mode=EscalationMode.SPECULATIVE,
            )
        )


def _features() -> QueryFeatures:
    return QueryFeatures(
        resolved_symbols=(),
        anchor_count=0,
        has_relational_verb=False,
        has_causal_marker=False,
        has_aggregation_marker=False,
        has_code_literal=False,
        token_count=1,
        interrogative=Interrogative.NONE,
    )


class _FakePolicy:
    """Test double implementing `RetrievalPolicyProtocol`."""

    def __init__(
        self,
        *,
        seeds: tuple[Seed, ...],
        bundle: ContextBundle,
        delay_ms: float = 0.0,
        seed_delay_ms: float = 0.0,
    ) -> None:
        self._seeds = seeds
        self._bundle = bundle
        self._delay_ms = delay_ms
        self._seed_delay_ms = seed_delay_ms
        self.call_count = 0
        self.seed_completed = False

    async def seed(self, req, graph):
        if self._seed_delay_ms:
            await asyncio.sleep(self._seed_delay_ms / 1000)
        self.seed_completed = True
        return self._seeds

    async def expand(self, seeds, graph, budget):
        from parrot.knowledge.retrieval.policies.base import Subgraph

        return Subgraph(nodes=tuple(s.node for s in seeds))

    async def prune(self, subgraph, budget):
        return subgraph

    async def assemble(self, subgraph, budget):
        self.call_count += 1
        if self._delay_ms:
            await asyncio.sleep(self._delay_ms / 1000)
        return self._bundle


def _decision(query_class: QueryClass, policy: str) -> RetrievalRoutingDecision:
    return RetrievalRoutingDecision(
        query_class=query_class, policy=policy, matched_rule="R1", features=_features()
    )


@pytest.mark.asyncio
async def test_escalation_stops_at_deadline_and_flags_truncated() -> None:
    symbols = _symbols_with("foo")
    insufficient_bundle = _bundle(())  # 0 units -> COVERAGE trigger
    slow_policy = _FakePolicy(
        seeds=(Seed(node=_node_ref("foo"), score=1.0),),
        bundle=insufficient_bundle,
        delay_ms=30,
    )
    bundle, _decision_result = await run_escalation_ladder(
        start_class=QueryClass.DIRECT_SYMBOL,
        decision=_decision(QueryClass.DIRECT_SYMBOL, "DirectSymbolPolicy"),
        policies={QueryClass.DIRECT_SYMBOL: slow_policy},
        req=RetrievalRequest(query="foo", workspace=None),
        budget=RetrievalBudget(deadline_ms=1),
        symbols=symbols,
    )
    assert bundle is not None
    assert bundle.truncated is True


@pytest.mark.asyncio
async def test_deadline_cancels_slow_seed_stage_not_just_assemble() -> None:
    """Regression (code review): the deadline must be enforced as a hard
    ceiling over the WHOLE seed->expand->prune->assemble pipeline, not
    just checked between stages — a slow `seed()` must be interruptible
    too, not only a slow `assemble()`."""
    symbols = _symbols_with("foo")
    insufficient_bundle = _bundle(())
    slow_seed_policy = _FakePolicy(
        seeds=(Seed(node=_node_ref("foo"), score=1.0),),
        bundle=insufficient_bundle,
        seed_delay_ms=50,
    )
    bundle, _decision_result = await run_escalation_ladder(
        start_class=QueryClass.DIRECT_SYMBOL,
        decision=_decision(QueryClass.DIRECT_SYMBOL, "DirectSymbolPolicy"),
        policies={QueryClass.DIRECT_SYMBOL: slow_seed_policy},
        req=RetrievalRequest(query="foo", workspace=None),
        budget=RetrievalBudget(deadline_ms=1),
        symbols=symbols,
    )
    assert bundle is not None
    assert bundle.truncated is True
    # The seed stage itself must have been cancelled mid-flight — it must
    # NOT have been allowed to run to completion despite the 50ms delay.
    assert slow_seed_policy.seed_completed is False


@pytest.mark.asyncio
async def test_budget_decrements_across_steps() -> None:
    symbols = _symbols_with("foo")
    insufficient = _bundle(())  # always triggers COVERAGE

    policies = {
        QueryClass.DIRECT_SYMBOL: _FakePolicy(
            seeds=(Seed(node=_node_ref("foo"), score=1.0),), bundle=insufficient, delay_ms=5
        ),
        QueryClass.LOCAL_FACT: _FakePolicy(
            seeds=(Seed(node=_node_ref("foo"), score=1.0),), bundle=insufficient, delay_ms=5
        ),
        QueryClass.RELATIONAL: _FakePolicy(
            seeds=(Seed(node=_node_ref("foo"), score=1.0),), bundle=insufficient, delay_ms=5
        ),
    }
    deadline_ms = 100
    _bundle_result, decision = await run_escalation_ladder(
        start_class=QueryClass.DIRECT_SYMBOL,
        decision=_decision(QueryClass.DIRECT_SYMBOL, "DirectSymbolPolicy"),
        policies=policies,
        req=RetrievalRequest(query="foo", workspace=None),
        budget=RetrievalBudget(deadline_ms=deadline_ms),
        symbols=symbols,
    )
    total_elapsed = sum(step.elapsed_ms for step in decision.escalations)
    assert total_elapsed < deadline_ms


@pytest.mark.asyncio
async def test_escalations_recorded_with_trigger_and_cost() -> None:
    symbols = _symbols_with("foo")
    insufficient = _bundle(())
    sufficient = _bundle((_unit("foo", "def foo(): pass"),))

    policies = {
        QueryClass.DIRECT_SYMBOL: _FakePolicy(
            seeds=(Seed(node=_node_ref("foo"), score=1.0),), bundle=insufficient
        ),
        QueryClass.LOCAL_FACT: _FakePolicy(
            seeds=(Seed(node=_node_ref("foo"), score=1.0),), bundle=sufficient
        ),
    }
    bundle, decision = await run_escalation_ladder(
        start_class=QueryClass.DIRECT_SYMBOL,
        decision=_decision(QueryClass.DIRECT_SYMBOL, "DirectSymbolPolicy"),
        policies=policies,
        req=RetrievalRequest(query="foo", workspace=None),
        budget=RetrievalBudget(deadline_ms=1000, allow_stale=True),
        symbols=symbols,
        sufficiency=SufficiencyCheck(min_units=1),
    )
    assert len(decision.escalations) == 1
    step = decision.escalations[0]
    assert step.trigger == SufficiencyTrigger.COVERAGE.value
    assert step.used is True
    assert step.policy_attempted == "VectorSeedPolicy"
    assert step.elapsed_ms >= 0.0
    assert bundle is sufficient


@pytest.mark.asyncio
async def test_unimplemented_rung_records_attempt_not_success() -> None:
    symbols = _symbols_with("foo")
    insufficient = _bundle(())

    policies = {
        QueryClass.LOCAL_FACT: _FakePolicy(
            seeds=(Seed(node=_node_ref("foo"), score=1.0),), bundle=insufficient
        ),
        # RELATIONAL deliberately absent — not in the v1 cut.
    }
    bundle, decision = await run_escalation_ladder(
        start_class=QueryClass.LOCAL_FACT,
        decision=_decision(QueryClass.LOCAL_FACT, "VectorSeedPolicy"),
        policies=policies,
        req=RetrievalRequest(query="foo", workspace=None),
        budget=RetrievalBudget(deadline_ms=1000),
        symbols=symbols,
        sufficiency=SufficiencyCheck(min_units=1),
    )
    assert len(decision.escalations) == 1
    step = decision.escalations[0]
    assert step.to_class == QueryClass.RELATIONAL
    assert step.policy_attempted == "PersonalizedPageRankPolicy"
    assert step.used is False
    assert bundle is not None
    assert bundle.units == insufficient.units
    assert bundle.truncated is True


@pytest.mark.asyncio
async def test_mode_off_runs_single_policy() -> None:
    symbols = _symbols_with("foo")
    insufficient = _bundle(())  # would normally trigger escalation

    direct_policy = _FakePolicy(
        seeds=(Seed(node=_node_ref("foo"), score=1.0),), bundle=insufficient
    )
    local_fact_policy = _FakePolicy(
        seeds=(Seed(node=_node_ref("foo"), score=1.0),), bundle=insufficient
    )
    policies = {
        QueryClass.DIRECT_SYMBOL: direct_policy,
        QueryClass.LOCAL_FACT: local_fact_policy,
    }
    _bundle_result, decision = await run_escalation_ladder(
        start_class=QueryClass.DIRECT_SYMBOL,
        decision=_decision(QueryClass.DIRECT_SYMBOL, "DirectSymbolPolicy"),
        policies=policies,
        req=RetrievalRequest(query="foo", workspace=None),
        budget=RetrievalBudget(),
        symbols=symbols,
        mode=EscalationMode.OFF,
    )
    assert direct_policy.call_count == 1
    assert local_fact_policy.call_count == 0
    assert decision.escalations == ()
