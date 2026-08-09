"""Topology guarantees for the Community Manager flow.

The first two tests here are the most valuable in the suite. Between them
they protect the design decision the whole flow rests on — that every routing
predicate is a CEL string, so the flow stays exportable and therefore
checkpointable — and the invariant that the declarative and executable graphs
say the same thing.
"""
from __future__ import annotations

import pytest

from parrot.bots.flows.flow.cel_evaluator import CELPredicateEvaluator
from parrot.bots.flows.flow.flow import NODE_REGISTRY
from parrot_saas.flows.community_manager import definition as topo
from parrot_saas.flows.community_manager.flow import (
    build_community_manager_flow,
    declared_edges,
    executable_edges,
)
from parrot_saas.flows.community_manager.models import (
    ContactCapture,
    CouponDecision,
    CouponIssued,
    GuardrailStatus,
    GuardrailVerdict,
    ReviewTriage,
    TriageAction,
)
from parrot_saas.tenancy.context import TenantContext


@pytest.fixture
def tenant() -> TenantContext:
    """A minimal tenant."""
    return TenantContext(tenant_id="bar-pepe", name="Bar Pepe")


@pytest.fixture
def flow(tenant: TenantContext):
    """A flow built with no dependencies wired in."""
    return build_community_manager_flow(tenant=tenant)


# ---------------------------------------------------------------------------
# The checkpointing guarantee
# ---------------------------------------------------------------------------


def test_flow_is_exportable(flow) -> None:
    """``to_definition()`` must not raise.

    This is the single most load-bearing test in the package. A flow whose
    edges carry Python-callable predicates raises ``FlowNotExportableError``
    here — and because ``run_flow`` calls the same path when ``checkpoint=True``,
    such a flow fails before executing a single node. Keeping this green is
    what keeps suspend/resume available.
    """
    exported = flow.to_definition()

    assert exported.flow == "cm.bar-pepe"
    assert len(exported.nodes) == len(topo.NODE_TYPES)


def test_every_predicate_is_a_cel_string() -> None:
    """No edge may carry a callable predicate."""
    for source, target, condition, predicate in topo.EDGES:
        assert predicate is None or isinstance(predicate, str), (
            f"edge {source}->{target} has a non-string predicate; that would "
            "disable checkpointing for the whole flow"
        )


def test_all_cel_predicates_compile() -> None:
    """Every predicate string must be valid CEL.

    An invalid expression raises at construction, but a flow is built per
    tenant per run — so without this test the failure would first appear in
    production rather than in CI.
    """
    for _, _, _, predicate in topo.EDGES:
        if predicate:
            CELPredicateEvaluator(predicate)


def test_declarative_and_executable_graphs_match(flow) -> None:
    """The imperative edge list must equal the declarative one.

    The two exist separately only because the definition-driven scheduler
    cannot fire this graph's OR-joins. They are built from the same tuple, and
    this test is what keeps that true.
    """
    assert executable_edges(flow) == declared_edges()


def test_all_node_types_are_registered() -> None:
    """Every node type the definition names must exist in NODE_REGISTRY."""
    for node_type in topo.NODE_TYPES.values():
        assert node_type in NODE_REGISTRY, f"{node_type} is not registered"


def test_node_types_are_namespaced() -> None:
    """``NODE_REGISTRY`` is process-global and shared with the dev flows."""
    for node_type in topo.NODE_TYPES.values():
        assert node_type.startswith("cm."), node_type


def test_registration_is_idempotent() -> None:
    """Re-importing the nodes package must not raise on duplicate names."""
    import importlib

    import parrot_saas.flows.community_manager.nodes as nodes_pkg

    importlib.reload(nodes_pkg)


# ---------------------------------------------------------------------------
# Graph shape
# ---------------------------------------------------------------------------


def test_close_is_an_or_join_with_six_predecessors(flow) -> None:
    """The OR-join is why explicit-edge mode is mandatory.

    Under the definition-driven AND-join scheduler ``close`` would wait for
    all six predecessors and never fire.
    """
    sources = {
        source
        for source, target, _, _ in topo.EDGES
        if target == topo.CLOSE
    }

    assert sources == {
        topo.TRIAGE,
        topo.GUARDRAIL,
        topo.CAPTURE_CONTACT,
        topo.COUPON_ELIGIBILITY,
        topo.COUPON_ISSUE,
        topo.COUPON_DELIVER,
    }


def test_flow_runs_in_explicit_edge_mode(flow) -> None:
    """Declaring edges is what unlocks OR-join and skip propagation."""
    assert flow._edges
    assert flow._definition is None


def test_repair_loop_back_edge_exists_and_is_conditional() -> None:
    """The guardrail->draft cycle must be an ``on_condition`` edge.

    ``_validate_acyclic`` exempts only ``on_condition`` edges, so any other
    condition would make the definition fail validation.
    """
    back_edges = [
        (condition, predicate)
        for source, target, condition, predicate in topo.EDGES
        if source == topo.GUARDRAIL and target == topo.REPLY_DRAFT
    ]

    assert back_edges == [("on_condition", topo.CEL_GUARDRAIL_REVISE)]


def test_every_middle_node_has_an_error_edge() -> None:
    """A node that can raise must route to the failure handler."""
    error_sources = {
        source
        for source, target, condition, _ in topo.EDGES
        if target == topo.FAILURE and condition == "on_error"
    }

    assert error_sources == set(topo.MIDDLE_NODES)


# ---------------------------------------------------------------------------
# Predicate behaviour against the real result models
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("predicate", "result", "expected"),
    [
        (topo.CEL_TRIAGE_REPLY, ReviewTriage(action=TriageAction.REPLY), True),
        (topo.CEL_TRIAGE_REPLY, ReviewTriage(action=TriageAction.SKIP), False),
        (topo.CEL_TRIAGE_SKIP, ReviewTriage(action=TriageAction.SKIP), True),
        (
            topo.CEL_GUARDRAIL_APPROVED,
            GuardrailVerdict(status=GuardrailStatus.APPROVED),
            True,
        ),
        (
            topo.CEL_GUARDRAIL_REVISE,
            GuardrailVerdict(status=GuardrailStatus.REVISE),
            True,
        ),
        (
            topo.CEL_GUARDRAIL_REVISE,
            GuardrailVerdict(status=GuardrailStatus.BLOCKED),
            False,
        ),
        (
            topo.CEL_GUARDRAIL_BLOCKED,
            GuardrailVerdict(status=GuardrailStatus.BLOCKED),
            True,
        ),
        (topo.CEL_HAS_CONTACT, ContactCapture(contact_available=True), True),
        (topo.CEL_NO_CONTACT, ContactCapture(contact_available=False), True),
        (topo.CEL_COUPON_ELIGIBLE, CouponDecision(eligible=True), True),
        (topo.CEL_COUPON_NOT_ELIGIBLE, CouponDecision(eligible=False), True),
        (topo.CEL_COUPON_ISSUED, CouponIssued(issued=True), True),
        (topo.CEL_COUPON_NOT_ISSUED, CouponIssued(issued=False), True),
    ],
)
def test_predicates_route_as_intended(predicate, result, expected) -> None:
    """Each predicate must evaluate as designed against its own model."""
    assert CELPredicateEvaluator(predicate)(result) is expected


def test_enums_dump_as_plain_values_not_members() -> None:
    """Enum fields must dump as their value, including on defaults.

    Being a ``str`` subclass is not sufficient: the engine coerces a result
    with ``model_dump()`` in Python mode, which returns the enum *member*, and
    celpy stringifies that as ``"TriageAction.REPLY"``. A predicate comparing
    against ``"reply"`` would then be false and the run would take the wrong
    branch with no error anywhere. ``CMResult`` sets ``use_enum_values``; the
    default case additionally needs ``validate_default``, which is why both
    are asserted here.
    """
    explicit = ReviewTriage(action=TriageAction.REPLY).model_dump()
    defaulted = ReviewTriage().model_dump()

    assert explicit["action"] == "reply"
    assert type(explicit["action"]) is str
    assert defaulted["action"] == "skip"
    assert type(defaulted["action"]) is str


def test_enum_fields_still_compare_against_enum_members() -> None:
    """Storing plain values must not break ergonomic comparisons."""
    verdict = GuardrailVerdict(status=GuardrailStatus.REVISE)

    assert verdict.status == GuardrailStatus.REVISE


def test_no_predicate_field_is_optional() -> None:
    """Fields a predicate reads must never be Optional.

    ``CELPredicateEvaluator`` coerces ``None`` to an empty string, so an
    optional routing field would silently compare as ``""`` and take the
    wrong branch rather than failing loudly.
    """
    checks = [
        (ReviewTriage, "action"),
        (GuardrailVerdict, "status"),
        (ContactCapture, "contact_available"),
        (CouponDecision, "eligible"),
        (CouponIssued, "issued"),
    ]
    for model, field_name in checks:
        field = model.model_fields[field_name]
        assert field.is_required() is False, f"{model.__name__}.{field_name}"
        assert field.default is not None, f"{model.__name__}.{field_name}"
