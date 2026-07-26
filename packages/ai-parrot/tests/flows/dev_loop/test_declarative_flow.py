"""Declarative dev-loop definition + factories + parity (FEAT-250 TASK-010)."""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

import pytest

from parrot.bots.flows.flow.flow import NODE_REGISTRY
from parrot.bots.flows.flow.cel_evaluator import CELPredicateEvaluator
from parrot.flows.dev_loop.definition import build_dev_loop_definition
from parrot.flows.dev_loop.factories import build_dev_loop_node_factories
from parrot.flows.dev_loop.flow import build_dev_loop_flow
from parrot.flows.dev_loop.models import (
    CodexCodeDispatchProfile,
    LLMCodeDispatchProfile,
    QAReport,
    WorkBrief,
)
from parrot.flows.dev_loop.nodes.bug_intake import BugIntakeNode
from parrot.flows.dev_loop.nodes.close import DevLoopCloseNode
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
from parrot.flows.dev_loop.nodes.failure_handler import FailureHandlerNode
from parrot.flows.dev_loop.nodes.intent_classifier import IntentClassifierNode
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.nodes.research import ResearchNode

_DEV_LOOP_TYPES = [
    "dev_loop.intent_classifier",
    "dev_loop.bug_intake",
    "dev_loop.research",
    "dev_loop.development",
    "dev_loop.qa",
    "dev_loop.deployment_handoff",
    "dev_loop.failure_handler",
    "dev_loop.close",
    "dev_loop.revision_handoff",  # FEAT-250 TASK-012
]


def _brief(kind: str) -> WorkBrief:
    from parrot.flows.dev_loop.models import FlowtaskCriterion

    return WorkBrief(
        kind=kind,
        summary="customer sync drops the last row sometimes",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[FlowtaskCriterion(name="run", task_path="a.yaml")],
        escalation_assignee="a",
        reporter="b",
    )


# ── registration ───────────────────────────────────────────────────────


def test_register_node_dev_loop_types():
    import parrot.flows.dev_loop.factories  # noqa: F401 - triggers registration

    for t in _DEV_LOOP_TYPES:
        assert t in NODE_REGISTRY


# ── definition validity ────────────────────────────────────────────────


def test_definition_is_valid_and_complete():
    defn = build_dev_loop_definition()
    ids = {n.id for n in defn.nodes}
    assert ids == {
        "intent_classifier",
        "bug_intake",
        "research",
        "development",
        "qa",
        "deployment_handoff",
        "failure_handler",
        "close",
    }
    # every node type is a registered dev_loop.* type
    assert all(n.type.startswith("dev_loop.") for n in defn.nodes)
    # the success path terminates at close
    assert any(e.from_ == "deployment_handoff" and e.to == "close" for e in defn.edges)


def test_definition_revision_graph():
    # FEAT-250 TASK-012 authored the revision graph.
    defn = build_dev_loop_definition(revision=True)
    ids = {n.id for n in defn.nodes}
    assert ids == {"development", "qa", "revision_handoff", "failure_handler", "close"}
    assert "research" not in ids and "intent_classifier" not in ids


# ── factories ──────────────────────────────────────────────────────────


def test_factories_cover_all_types_and_construct_nodes():
    factories = build_dev_loop_node_factories(dispatcher=MagicMock(), jira_toolkit=MagicMock(), redis_url="redis://x")
    assert set(factories) == set(_DEV_LOOP_TYPES)
    defn = build_dev_loop_definition()
    by_id = {n.id: n for n in defn.nodes}
    node = factories["dev_loop.research"](by_id["research"], {"intent_classifier"}, {"development"})
    assert node.node_id == "research"
    assert "intent_classifier" in node.dependencies
    assert "development" in node.successors


def test_development_factory_accepts_alternate_dispatcher():
    default_dispatcher = MagicMock()
    development_dispatcher = MagicMock()
    development_profile = CodexCodeDispatchProfile()
    factories = build_dev_loop_node_factories(
        dispatcher=default_dispatcher,
        development_dispatcher=development_dispatcher,
        development_profile=development_profile,
        jira_toolkit=MagicMock(),
        redis_url="redis://x",
    )
    defn = build_dev_loop_definition()
    by_id = {n.id: n for n in defn.nodes}

    node = factories["dev_loop.development"](by_id["development"], {"research"}, {"qa"})

    assert isinstance(node, DevelopmentNode)
    assert node._dispatcher is development_dispatcher
    assert node._dispatch_profile is development_profile


def test_development_factory_accepts_llm_dispatch_profile():
    default_dispatcher = MagicMock()
    development_dispatcher = MagicMock()
    development_profile = LLMCodeDispatchProfile(llm="nvidia:z-ai/glm-5.1")
    factories = build_dev_loop_node_factories(
        dispatcher=default_dispatcher,
        development_dispatcher=development_dispatcher,
        development_profile=development_profile,
        jira_toolkit=MagicMock(),
        redis_url="redis://x",
    )
    defn = build_dev_loop_definition()
    by_id = {n.id: n for n in defn.nodes}

    node = factories["dev_loop.development"](by_id["development"], {"research"}, {"qa"})

    assert isinstance(node, DevelopmentNode)
    assert node._dispatcher is development_dispatcher
    assert node._dispatch_profile is development_profile


# ── CEL parity with the legacy Python callables ────────────────────────


def test_cel_predicates_match_legacy_semantics():
    assert CELPredicateEvaluator('result.kind == "bug"')(_brief("bug")) is True
    assert CELPredicateEvaluator('result.kind == "bug"')(_brief("enhancement")) is False
    assert CELPredicateEvaluator('result.kind != "bug"')(_brief("enhancement")) is True
    passed = QAReport(passed=True, criterion_results=[], lint_passed=True)
    failed = QAReport(passed=False, criterion_results=[], lint_passed=True)
    assert CELPredicateEvaluator("result.passed == true")(passed) is True
    assert CELPredicateEvaluator("result.passed == true")(failed) is False
    assert CELPredicateEvaluator("result.passed == false")(failed) is True


# ── end-to-end routing parity (drives the real build_dev_loop_flow) ─────


def _stub_executes(
    monkeypatch, *, intent_kind: str, qa_passed: bool, qa_attempt: Optional[int] = None
):
    """Patch each node class' execute with a lightweight typed stub.

    Args:
        qa_passed: The QA verdict every dispatch returns.
        qa_attempt: Attempt number stamped on a FAILING QAReport (FEAT-377
            TASK-1910). ``None`` (default) stamps the exhaustion threshold
            (``conf.DEV_LOOP_QA_MAX_RETRIES``) so a persistently-failing stub
            routes straight to ``failure_handler`` — matching this
            function's pre-TASK-1910 behavior (attempt-stamping/retry-then-
            pass sequencing is exercised by ``qa_exec_sequence`` below, and
            e2e feedback/worktree-reuse behavior is TASK-1911's).
    """
    from parrot import conf
    from parrot.flows.dev_loop.models import (
        DevelopmentOutput,
        ResearchOutput,
    )

    brief = _brief(intent_kind)
    attempt = qa_attempt if qa_attempt is not None else int(conf.DEV_LOOP_QA_MAX_RETRIES)

    async def intent_exec(self, ctx, deps=None, **kw):
        return brief

    async def bug_exec(self, ctx, deps=None, **kw):
        return brief

    async def research_exec(self, ctx, deps=None, **kw):
        return ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="x",
            feat_id="FEAT-1",
            branch_name="feat-1-x",
            worktree_path="/tmp/feat-1-x",
        )

    async def dev_exec(self, ctx, deps=None, **kw):
        return DevelopmentOutput(files_changed=[], commit_shas=[], summary="ok")

    async def qa_exec(self, ctx, deps=None, **kw):
        return QAReport(
            passed=qa_passed, criterion_results=[], lint_passed=qa_passed,
            attempt=1 if qa_passed else attempt,
        )

    async def handoff_exec(self, ctx, deps=None, **kw):
        return {"status": "ready_to_deploy", "pr_url": "u", "pr_number": 1}

    async def failure_exec(self, ctx, deps=None, **kw):
        return {"status": "escalated"}

    async def close_exec(self, ctx, deps=None, **kw):
        return {"status": "closed"}

    monkeypatch.setattr(IntentClassifierNode, "execute", intent_exec)
    monkeypatch.setattr(BugIntakeNode, "execute", bug_exec)
    monkeypatch.setattr(ResearchNode, "execute", research_exec)
    monkeypatch.setattr(DevelopmentNode, "execute", dev_exec)
    monkeypatch.setattr(QANode, "execute", qa_exec)
    monkeypatch.setattr(DeploymentHandoffNode, "execute", handoff_exec)
    monkeypatch.setattr(FailureHandlerNode, "execute", failure_exec)
    monkeypatch.setattr(DevLoopCloseNode, "execute", close_exec)


def _stub_executes_qa_sequence(monkeypatch, *, intent_kind: str, qa_reports: list):
    """Like ``_stub_executes``, but QA returns one entry of ``qa_reports``
    per dispatch (in order) — drives a genuine retry-then-pass/exhaust
    sequence through the REAL ``build_dev_loop_flow()`` wiring."""
    from parrot.flows.dev_loop.models import DevelopmentOutput, ResearchOutput

    brief = _brief(intent_kind)
    calls = {"qa": 0}

    async def intent_exec(self, ctx, deps=None, **kw):
        return brief

    async def bug_exec(self, ctx, deps=None, **kw):
        return brief

    async def research_exec(self, ctx, deps=None, **kw):
        return ResearchOutput(
            jira_issue_key="OPS-1", spec_path="x", feat_id="FEAT-1",
            branch_name="feat-1-x", worktree_path="/tmp/feat-1-x",
        )

    async def dev_exec(self, ctx, deps=None, **kw):
        return DevelopmentOutput(files_changed=[], commit_shas=[], summary="ok")

    async def qa_exec(self, ctx, deps=None, **kw):
        report = qa_reports[calls["qa"]]
        calls["qa"] += 1
        return report

    async def handoff_exec(self, ctx, deps=None, **kw):
        return {"status": "ready_to_deploy", "pr_url": "u", "pr_number": 1}

    async def failure_exec(self, ctx, deps=None, **kw):
        return {"status": "escalated"}

    async def close_exec(self, ctx, deps=None, **kw):
        return {"status": "closed"}

    monkeypatch.setattr(IntentClassifierNode, "execute", intent_exec)
    monkeypatch.setattr(BugIntakeNode, "execute", bug_exec)
    monkeypatch.setattr(ResearchNode, "execute", research_exec)
    monkeypatch.setattr(DevelopmentNode, "execute", dev_exec)
    monkeypatch.setattr(QANode, "execute", qa_exec)
    monkeypatch.setattr(DeploymentHandoffNode, "execute", handoff_exec)
    monkeypatch.setattr(FailureHandlerNode, "execute", failure_exec)
    monkeypatch.setattr(DevLoopCloseNode, "execute", close_exec)
    return calls


def _flow():
    return build_dev_loop_flow(
        dispatcher=MagicMock(),
        jira_toolkit=MagicMock(),
        log_toolkits={},
        redis_url="redis://x",
        publish_flow_events=False,
        lifecycle_events=False,
    )


def _ran(result) -> set:
    nr = getattr(result, "node_results", None)
    if isinstance(nr, dict):
        return set(nr.keys())
    return set(getattr(result, "results", {}).keys())


@pytest.mark.asyncio
async def test_routing_non_bug_skips_bug_intake(monkeypatch):
    _stub_executes(monkeypatch, intent_kind="enhancement", qa_passed=True)
    flow = _flow()
    res = await flow.run_flow("go")
    ran = _ran(res)
    assert {"intent_classifier", "research", "development", "qa", "deployment_handoff", "close"}.issubset(ran)
    assert "bug_intake" not in ran
    assert "failure_handler" not in ran


@pytest.mark.asyncio
async def test_routing_bug_runs_bug_intake(monkeypatch):
    _stub_executes(monkeypatch, intent_kind="bug", qa_passed=True)
    flow = _flow()
    res = await flow.run_flow("go")
    ran = _ran(res)
    assert {"intent_classifier", "bug_intake", "research", "development", "qa", "deployment_handoff", "close"}.issubset(
        ran
    )
    assert "failure_handler" not in ran


@pytest.mark.asyncio
async def test_routing_qa_fail_goes_to_failure(monkeypatch):
    # FEAT-377 TASK-1910: a persistently-failing QA (stamped at the
    # exhaustion threshold) still reaches failure_handler — the repair
    # loop only defers escalation, it doesn't remove it.
    _stub_executes(monkeypatch, intent_kind="enhancement", qa_passed=False)
    flow = _flow()
    res = await flow.run_flow("go")
    ran = _ran(res)
    assert "failure_handler" in ran
    assert "deployment_handoff" not in ran
    assert "close" not in ran


# ── QA repair loop (FEAT-377 TASK-1910) ──────────────────────────────────


def test_qa_report_attempt_default_is_1():
    assert QAReport(passed=False, criterion_results=[], lint_passed=False).attempt == 1


def test_qa_retry_edge_routes_to_development():
    """A failing QAReport below the retry cap fires the retry predicate
    (both topology forms), never the exhaustion one."""
    from parrot import conf
    from parrot.flows.dev_loop.definition import _cel_qa_exhausted, _cel_qa_retry
    from parrot.flows.dev_loop.flow import _make_qa_exhausted, _make_qa_retry

    n = int(conf.DEV_LOOP_QA_MAX_RETRIES)
    failing_attempt_1 = QAReport(passed=False, criterion_results=[], lint_passed=False, attempt=1)

    assert CELPredicateEvaluator(_cel_qa_retry(n))(failing_attempt_1) is True
    assert CELPredicateEvaluator(_cel_qa_exhausted(n))(failing_attempt_1) is False
    assert _make_qa_retry(n)(failing_attempt_1) is True
    assert _make_qa_exhausted(n)(failing_attempt_1) is False


def test_qa_exhausted_edge_routes_to_failure():
    """A failing QAReport at/above the retry cap fires the exhaustion
    predicate (both topology forms), never the retry one."""
    from parrot import conf
    from parrot.flows.dev_loop.definition import _cel_qa_exhausted, _cel_qa_retry
    from parrot.flows.dev_loop.flow import _make_qa_exhausted, _make_qa_retry

    n = int(conf.DEV_LOOP_QA_MAX_RETRIES)
    exhausted_report = QAReport(passed=False, criterion_results=[], lint_passed=False, attempt=n)

    assert CELPredicateEvaluator(_cel_qa_exhausted(n))(exhausted_report) is True
    assert CELPredicateEvaluator(_cel_qa_retry(n))(exhausted_report) is False
    assert _make_qa_exhausted(n)(exhausted_report) is True
    assert _make_qa_retry(n)(exhausted_report) is False


def test_definition_flow_parity_includes_retry_edge():
    """The declarative definition and the imperative flow.py wiring must
    agree edge-for-edge on the new qa <-> development repair-loop edges
    (FEAT-250 parity discipline, extended by FEAT-377 TASK-1910)."""
    defn = build_dev_loop_definition()
    qa_edges = {(e.from_, e.to, e.condition) for e in defn.edges if e.from_ == "qa"}
    assert ("qa", "deployment_handoff", "on_condition") in qa_edges
    assert ("qa", "development", "on_condition") in qa_edges
    assert ("qa", "failure_handler", "on_condition") in qa_edges
    # Exactly one on_condition QA edge per outcome — no duplicate/missing routes.
    on_condition_targets = {to for (_, to, cond) in qa_edges if cond == "on_condition"}
    assert on_condition_targets == {"deployment_handoff", "development", "failure_handler"}

    # flow.py wires the identical three targets off "qa" (verified by
    # inspecting the real AgentsFlow's registered edges).
    flow = _flow()
    flow_qa_targets = {
        e.to for e in flow._edges  # type: ignore[attr-defined]
        if e.from_ == "qa" and e.condition == "on_condition"
    }
    assert flow_qa_targets == {"deployment_handoff", "development", "failure_handler"}


@pytest.mark.asyncio
async def test_routing_qa_retry_then_pass_reaches_close(monkeypatch):
    """FEAT-377 TASK-1910: the real build_dev_loop_flow() wiring supports a
    genuine repair-loop re-entry — QA fails on attempt 1, retries
    development, passes on attempt 2, reaches close."""
    calls = _stub_executes_qa_sequence(
        monkeypatch,
        intent_kind="enhancement",
        qa_reports=[
            QAReport(passed=False, criterion_results=[], lint_passed=False, attempt=1),
            QAReport(passed=True, criterion_results=[], lint_passed=True, attempt=2),
        ],
    )
    flow = _flow()
    res = await flow.run_flow("go")
    ran = _ran(res)
    assert "close" in ran
    assert "failure_handler" not in ran
    assert calls["qa"] == 2


@pytest.mark.asyncio
async def test_routing_qa_exhausts_after_max_retries(monkeypatch):
    """FEAT-377 TASK-1910: QA fails every attempt up to the cap, then
    escalates to failure_handler — the loop is bounded, not infinite."""
    from parrot import conf

    n = int(conf.DEV_LOOP_QA_MAX_RETRIES)
    reports = [
        QAReport(passed=False, criterion_results=[], lint_passed=False, attempt=a)
        for a in range(1, n + 1)
    ]
    calls = _stub_executes_qa_sequence(
        monkeypatch, intent_kind="enhancement", qa_reports=reports,
    )
    flow = _flow()
    res = await flow.run_flow("go")
    ran = _ran(res)
    assert "failure_handler" in ran
    assert "close" not in ran
    assert calls["qa"] == n
