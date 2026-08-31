"""FEAT-479 §4 end-to-end integration tests — the whole chain: builder →
adapter → dispatcher → event → subscriber → ledger → report.

Every unit test elsewhere in this feature verifies one seam. These four
verify the chain end to end, against a real ``DevLoopRunner``/
``DevFlowRunner``, a real flow built by ``build_dev_flow``/
``build_dev_loop_flow`` (so the FlowLifecycleAdapter attachment and the
per-run ``EventRegistry`` creation are genuinely exercised, not assumed),
and a scriptable fake dispatcher that emits real lifecycle events on the
run's injected registry — mirroring exactly what a real
``LLMCodeDispatcher``/``ClaudeCodeDispatcher`` does. No network, no Redis,
no subprocess, no real LLM call; no ``asyncio.sleep`` — the ledger must
already be populated when the awaited dispatch/registry emit returns
(spec §2 Exactness).

Each test asserts on the *rendered* report (parsed from the persisted
``usage.json`` / re-rendered via ``render_usage_markdown``), not only
internal state — that is what the user actually sees.

| Test | Proves |
|---|---|
| ``test_dev_flow_run_produces_usage_report`` | Finding 1 — dev-flow emitted nothing at all |
| ``test_retry_cycle_totals_are_cumulative`` | Finding 2 — retries overwrote |
| ``test_pool_run_attributes_every_worker`` | Finding 3 — pool workers were dropped |
| ``test_failed_node_reported_with_usage`` | the failure-reporting goal |
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot import conf
from parrot.core.events.lifecycle.events.client import (
    AfterClientCallEvent,
    ClientCallFailedEvent,
)
from parrot.flows.dev_flow.flow import build_dev_flow
from parrot.flows.dev_flow.runner import DevFlowRunner
from parrot.flows.dev_loop import (
    BugBrief,
    DevLoopRunner,
    QAReport,
    ResearchOutput,
    ShellCriterion,
    build_dev_loop_flow,
)
from parrot.flows.dev_loop.models import (
    DevelopmentOutput,
    FeatureBrief,
    FeedbackDecision,
    PlannerOutput,
    SynthesisReport,
)
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
from parrot.flows.dev_loop.nodes.feature_handoff import FeatureHandoffNode
from parrot.flows.dev_loop.nodes.feedback_router import FeedbackRouterNode
from parrot.flows.dev_loop.nodes.planner import PlannerNode
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.nodes.synthesis import SynthesisNode
from parrot.flows.dev_loop.usage_report import UsageReport, render_usage_markdown
from parrot.observability.context import usage_attribution

# ---------------------------------------------------------------------------
# The scriptable fake dispatcher — emits REAL lifecycle events on the run's
# injected per-run registry (spec §2 Exactness: `await registry.emit(...)`,
# never `emit_nowait`), exactly mirroring a real dispatcher's `_emit_after_
# call`/`_emit_failed_call`. Constructed with `set_event_registry_resolver`,
# same shape as LLMCodeDispatcher/ClaudeCodeDispatcher (TASK-2616/2617), so
# DevLoopRunner.__init__'s existing hasattr-guarded wiring picks it up with
# zero changes to production code.
# ---------------------------------------------------------------------------


class _ScriptedDispatcher:
    """Fake in-process dispatcher used from stubbed node ``execute()``s.

    Not the ``AbstractTool``/``AbstractClient`` machinery — this stands in
    for whatever real dispatcher a node would normally call, so the tests
    control exactly which tokens/model/failure each dispatch reports
    without needing a real LLM, subprocess, or network call.
    """

    def __init__(self, *, model: str = "test-model") -> None:
        self._model = model
        self._event_registry_resolver = None

    def set_event_registry_resolver(self, resolver) -> None:
        self._event_registry_resolver = resolver

    async def emit_usage(
        self, *, run_id: str, node_id: str, input_tokens: int, output_tokens: int
    ) -> None:
        """Emit a real AfterClientCallEvent — awaited, exact (spec §2)."""
        if self._event_registry_resolver is None:
            return
        registry = self._event_registry_resolver(run_id)
        if registry is None:
            return
        with usage_attribution(run_id, node_id):
            await registry.emit(
                AfterClientCallEvent(
                    trace_context=TraceContext.new_root(),
                    client_name="fake",
                    model=self._model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    duration_ms=10.0,
                )
            )

    async def emit_failure(self, *, run_id: str, node_id: str, error_type: str) -> None:
        """Emit a real ClientCallFailedEvent — awaited, exact."""
        if self._event_registry_resolver is None:
            return
        registry = self._event_registry_resolver(run_id)
        if registry is None:
            return
        with usage_attribution(run_id, node_id):
            await registry.emit(
                ClientCallFailedEvent(
                    trace_context=TraceContext.new_root(),
                    client_name="fake",
                    model=self._model,
                    error_type=error_type,
                )
            )


def _usage_report_from_disk(run_id: str) -> UsageReport:
    """Read the persisted ``usage.json`` this run wrote (via ``conftest.py``'s
    autouse ``_isolate_dev_loop_run_artifacts`` fixture redirecting
    ``conf.OUTPUT_DIR`` to a tmp dir) and parse it back into a
    :class:`UsageReport` — the deliverable the user actually reads."""
    path = Path(conf.OUTPUT_DIR) / "dev_loop_runs" / f"{run_id}.usage.json"
    assert path.exists(), f"{path} was never written"
    return UsageReport.model_validate_json(path.read_text())


@pytest.fixture(autouse=True)
def _patch_worktree_base(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Test 1 — Finding 1: dev-flow emitted zero lifecycle events (no adapter).
# ---------------------------------------------------------------------------


def _stub_dev_flow_executes(monkeypatch, fake: _ScriptedDispatcher, *, qa_passed: bool = True) -> None:
    """Stub every dev-flow node's business logic, but route usage through
    the real per-run registry — mirrors ``test_feature_flow.py``'s own
    ``_stub_feature_executes`` precedent, extended to emit real events."""

    async def planner_exec(self, ctx, deps=None, **kw):
        shared = self.shared_state(ctx)
        run_id = shared["run_id"]
        await fake.emit_usage(run_id=run_id, node_id=self.name, input_tokens=300, output_tokens=120)
        out = PlannerOutput(
            spec_path="sdd/specs/x.spec.md",
            task_index_path="/tmp/sdd/tasks/index/x.json",
            feat_id="FEAT-999",
            branch_name="feat-999-x",
            worktree_path="/tmp/feat-999-x",
        )
        shared["planner_output"] = out
        return out

    async def dev_exec(self, ctx, deps=None, **kw):
        shared = self.shared_state(ctx)
        run_id = shared["run_id"]
        await fake.emit_usage(run_id=run_id, node_id=self.name, input_tokens=1000, output_tokens=500)
        out = DevelopmentOutput(files_changed=["a.py"], commit_shas=["abc"], summary="ok")
        shared["development_output"] = out
        return out

    async def synthesis_exec(self, ctx, deps=None, **kw):
        shared = self.shared_state(ctx)
        run_id = shared["run_id"]
        await fake.emit_usage(run_id=run_id, node_id=self.name, input_tokens=150, output_tokens=60)
        out = SynthesisReport(consistent=True, adjustments=[], summary="clean")
        shared["synthesis_report"] = out
        return out

    async def qa_exec(self, ctx, deps=None, **kw):
        shared = self.shared_state(ctx)
        run_id = shared["run_id"]
        await fake.emit_usage(run_id=run_id, node_id=self.name, input_tokens=200, output_tokens=80)
        return QAReport(passed=qa_passed, criterion_results=[], lint_passed=qa_passed)

    async def handoff_exec(self, ctx, deps=None, **kw):
        return {
            "status": "ready_to_deploy", "pr_url": "u", "pr_number": 1,
            "docs_path": "docs/features/feat-999-x.md", "wiki_page_id": None,
        }

    async def close_exec(self, ctx, deps=None, **kw):
        return {"status": "closed"}

    monkeypatch.setattr(PlannerNode, "execute", planner_exec)
    monkeypatch.setattr(DevelopmentNode, "execute", dev_exec)
    monkeypatch.setattr(SynthesisNode, "execute", synthesis_exec)
    monkeypatch.setattr(QANode, "execute", qa_exec)
    monkeypatch.setattr(FeatureHandoffNode, "execute", handoff_exec)

    from parrot.flows.dev_loop.nodes.close import DevLoopCloseNode

    monkeypatch.setattr(DevLoopCloseNode, "execute", close_exec)


async def test_dev_flow_run_produces_usage_report(monkeypatch, tmp_path):
    """Finding 1: dev-flow attached no FlowLifecycleAdapter (TASK-2611 fixed
    it) and DevFlowRunner.run() never created a per-run registry at all
    (a gap found while writing THIS test — see Completion Note; fixed in
    dev_flow/runner.py). Before both fixes this report was always empty."""
    fake = _ScriptedDispatcher()
    _stub_dev_flow_executes(monkeypatch, fake, qa_passed=True)

    flow = build_dev_flow(dispatcher=fake, redis_url="redis://x", publish_flow_events=False)
    runner = DevFlowRunner(flow, dispatcher=fake, redis_url="redis://x")

    doc = tmp_path / "x.proposal.md"
    doc.write_text("# proposal", encoding="utf-8")
    brief = FeatureBrief(document_path=str(doc), document_kind="proposal")

    result = await runner.run(brief, run_id="run-devflow-1")
    assert result is not None

    report = _usage_report_from_disk("run-devflow-1")
    assert report.agents, "dev-flow produced no usage records at all"
    assert not report.partial
    md = render_usage_markdown(report)
    assert "## Usage" in md
    assert "development" in md


# ---------------------------------------------------------------------------
# Test 2 — Finding 2: session state overwrote per-node tokens on retry.
# ---------------------------------------------------------------------------


def _stub_feature_executes_with_retry(
    monkeypatch, fake: _ScriptedDispatcher, dev_tokens: list[tuple[int, int]],
) -> dict[str, int]:
    """Mirrors ``test_feature_flow.py``'s ``_stub_feature_executes``, but
    ``development`` reports a DIFFERENT token count each cycle (scripted by
    ``dev_tokens``), and QA fails on cycle 1, forcing exactly one retry
    (FeedbackDecision "retry" then "escalate", matching the project's own
    FEAT-377/A precedent) before development runs a second time."""
    from parrot.flows.dev_loop.nodes.failure_handler import FailureHandlerNode
    from parrot.flows.dev_loop.nodes.intent_classifier import IntentClassifierNode

    calls = {"development": 0, "qa": 0, "feedback_router": 0}

    async def intent_exec(self, ctx, deps=None, **kw):
        return self.shared_state(ctx)["feature_brief"]

    async def planner_exec(self, ctx, deps=None, **kw):
        shared = self.shared_state(ctx)
        run_id = shared["run_id"]
        await fake.emit_usage(run_id=run_id, node_id=self.name, input_tokens=100, output_tokens=40)
        out = PlannerOutput(
            spec_path="sdd/specs/x.spec.md", task_index_path="/tmp/x.json",
            feat_id="FEAT-999", branch_name="feat-999-x", worktree_path="/tmp/feat-999-x",
        )
        shared["planner_output"] = out
        return out

    async def dev_exec(self, ctx, deps=None, **kw):
        shared = self.shared_state(ctx)
        run_id = shared["run_id"]
        idx = min(calls["development"], len(dev_tokens) - 1)
        inp, outp = dev_tokens[idx]
        calls["development"] += 1
        await fake.emit_usage(run_id=run_id, node_id=self.name, input_tokens=inp, output_tokens=outp)
        out = DevelopmentOutput(files_changed=["a.py"], commit_shas=["abc"], summary="ok")
        shared["development_output"] = out
        return out

    async def synthesis_exec(self, ctx, deps=None, **kw):
        shared = self.shared_state(ctx)
        run_id = shared["run_id"]
        await fake.emit_usage(run_id=run_id, node_id=self.name, input_tokens=50, output_tokens=20)
        out = SynthesisReport(consistent=True, adjustments=[], summary="clean")
        shared["synthesis_report"] = out
        return out

    async def qa_exec(self, ctx, deps=None, **kw):
        shared = self.shared_state(ctx)
        run_id = shared["run_id"]
        passed = calls["qa"] >= 1  # fails cycle 1, passes cycle 2
        calls["qa"] += 1
        await fake.emit_usage(run_id=run_id, node_id=self.name, input_tokens=80, output_tokens=30)
        return QAReport(passed=passed, criterion_results=[], lint_passed=passed)

    async def feedback_exec(self, ctx, deps=None, **kw):
        decision = "retry" if calls["feedback_router"] == 0 else "escalate"
        calls["feedback_router"] += 1
        out = FeedbackDecision(decision=decision, notes="")
        self.shared_state(ctx)["feedback_decision"] = out
        return out

    async def handoff_exec(self, ctx, deps=None, **kw):
        return {
            "status": "ready_to_deploy", "pr_url": "u", "pr_number": 1,
            "docs_path": "d", "wiki_page_id": None,
        }

    async def failure_exec(self, ctx, deps=None, **kw):
        return {"status": "escalated"}

    async def close_exec(self, ctx, deps=None, **kw):
        return {"status": "closed"}

    monkeypatch.setattr(IntentClassifierNode, "execute", intent_exec)
    monkeypatch.setattr(PlannerNode, "execute", planner_exec)
    monkeypatch.setattr(DevelopmentNode, "execute", dev_exec)
    monkeypatch.setattr(SynthesisNode, "execute", synthesis_exec)
    monkeypatch.setattr(QANode, "execute", qa_exec)
    monkeypatch.setattr(FeedbackRouterNode, "execute", feedback_exec)
    monkeypatch.setattr(FeatureHandoffNode, "execute", handoff_exec)
    monkeypatch.setattr(FailureHandlerNode, "execute", failure_exec)

    from parrot.flows.dev_loop.nodes.close import DevLoopCloseNode

    monkeypatch.setattr(DevLoopCloseNode, "execute", close_exec)
    return calls


async def test_retry_cycle_totals_are_cumulative(monkeypatch, tmp_path):
    """Finding 2: session state's ``_with_dispatch`` merges into one
    ``DispatchState`` per node, so a second ``dispatch/completed`` replaced
    the first's token counts. The ledger appends instead — a 2-cycle run
    must report the SUM, not the last cycle's numbers."""
    fake = _ScriptedDispatcher()
    dev_tokens = [(1000, 500), (2000, 700)]
    calls = _stub_feature_executes_with_retry(monkeypatch, fake, dev_tokens)

    runner = DevLoopRunner(AsyncMock(), dispatcher=fake, redis_url="redis://x")

    doc = tmp_path / "x.proposal.md"
    doc.write_text("# p", encoding="utf-8")
    brief = FeatureBrief(document_path=str(doc), document_kind="proposal")

    await runner.run(brief, run_id="run-retry-1")

    # The observable proof a real re-entrant loop happened (mirrors
    # test_feature_flow.py::test_feature_flow_feedback_retry).
    assert calls["development"] == 2

    report = _usage_report_from_disk("run-retry-1")
    dev = next(a for a in report.agents if a.seat == "development")
    assert len(dev.cycles) == 2
    assert dev.input_tokens == sum(c.input_tokens for c in dev.cycles)
    assert dev.input_tokens == 3000  # not 2000 (the last cycle alone)
    assert dev.output_tokens == 1200


# ---------------------------------------------------------------------------
# Test 3 — Finding 3: pool-worker seats silently dropped.
# ---------------------------------------------------------------------------


def _stub_bug_mode_pool_executes(monkeypatch, fake: _ScriptedDispatcher) -> None:
    """Stubs the bug-mode graph's nodes; ``development`` simulates a
    2-worker ``DevAgentPool`` fan-out by emitting two separate
    AfterClientCallEvents under ``"development.w1"``/``"development.w2"``
    seats — the exact scheme ``agent_pool.py``'s ``worker_id =
    f"development.w{i}"`` uses — rather than driving the pool
    scheduler's task-index machinery (orthogonal to this feature)."""
    from parrot.flows.dev_loop.nodes.bug_intake import BugIntakeNode
    from parrot.flows.dev_loop.nodes.intent_classifier import IntentClassifierNode
    from parrot.flows.dev_loop.nodes.research import ResearchNode

    async def intent_exec(self, ctx, deps=None, **kw):
        return self.shared_state(ctx)["bug_brief"]

    async def bug_intake_exec(self, ctx, deps=None, **kw):
        return self.shared_state(ctx)["bug_brief"]

    async def research_exec(self, ctx, deps=None, **kw):
        shared = self.shared_state(ctx)
        run_id = shared["run_id"]
        await fake.emit_usage(run_id=run_id, node_id=self.name, input_tokens=50, output_tokens=20)
        out = ResearchOutput(
            jira_issue_key="OPS-1", spec_path="sdd/specs/x.spec.md", feat_id="FEAT-130",
            branch_name="feat-130-fix", worktree_path=str(shared.get("_tmp_path", ".")),
            log_excerpts=[],
        )
        shared["research_output"] = out
        return out

    async def dev_exec(self, ctx, deps=None, **kw):
        shared = self.shared_state(ctx)
        run_id = shared["run_id"]
        await fake.emit_usage(
            run_id=run_id, node_id="development.w1", input_tokens=100, output_tokens=50,
        )
        await fake.emit_usage(
            run_id=run_id, node_id="development.w2", input_tokens=200, output_tokens=60,
        )
        out = DevelopmentOutput(files_changed=["a.py", "b.py"], commit_shas=["a1", "b2"], summary="fanned out")
        shared["development_output"] = out
        return out

    async def qa_exec(self, ctx, deps=None, **kw):
        shared = self.shared_state(ctx)
        run_id = shared["run_id"]
        await fake.emit_usage(run_id=run_id, node_id=self.name, input_tokens=30, output_tokens=10)
        return QAReport(passed=True, criterion_results=[], lint_passed=True)

    async def handoff_exec(self, ctx, deps=None, **kw):
        return {"status": "ready_to_deploy", "pr_url": "u"}

    async def close_exec(self, ctx, deps=None, **kw):
        return {"status": "closed"}

    monkeypatch.setattr(IntentClassifierNode, "execute", intent_exec)
    monkeypatch.setattr(BugIntakeNode, "execute", bug_intake_exec)
    monkeypatch.setattr(ResearchNode, "execute", research_exec)
    monkeypatch.setattr(DevelopmentNode, "execute", dev_exec)
    monkeypatch.setattr(QANode, "execute", qa_exec)
    monkeypatch.setattr(DeploymentHandoffNode, "execute", handoff_exec)

    from parrot.flows.dev_loop.nodes.close import DevLoopCloseNode

    monkeypatch.setattr(DevLoopCloseNode, "execute", close_exec)


@pytest.fixture
def bug_brief() -> BugBrief:
    return BugBrief(
        summary="Customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[ShellCriterion(name="lint", command="ruff check .")],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


async def test_pool_run_attributes_every_worker(monkeypatch, bug_brief):
    """Finding 3: ``development.w1``/``.w2`` cannot validate against the
    closed ``NodeId`` Literal, so ``_apply_to_session_host`` swallowed them
    at DEBUG and fan-out usage was silently lost. The ledger keys seats by
    a free string — both workers must reach the report with their own
    model/tokens, rolled up under ``node_id="development"``."""
    fake = _ScriptedDispatcher()
    _stub_bug_mode_pool_executes(monkeypatch, fake)

    flow = build_dev_loop_flow(
        dispatcher=fake, jira_toolkit=AsyncMock(), log_toolkits={},
        redis_url="redis://x", publish_flow_events=False,
    )
    runner = DevLoopRunner(flow, dispatcher=fake, redis_url="redis://x")

    await runner.run(bug_brief, run_id="run-pool-1")

    report = _usage_report_from_disk("run-pool-1")
    md = render_usage_markdown(report)
    assert "development.w1" in md and "development.w2" in md
    seats = {a.seat: a for a in report.agents}
    assert seats["development.w1"].node_id == "development"
    assert seats["development.w2"].node_id == "development"
    assert seats["development.w1"].input_tokens == 100
    assert seats["development.w2"].input_tokens == 200


# ---------------------------------------------------------------------------
# Test 4 — a failed cycle must report its error AND the tokens it burned.
# ---------------------------------------------------------------------------


def _stub_bug_mode_qa_failure(monkeypatch, fake: _ScriptedDispatcher) -> None:
    from parrot.flows.dev_loop.nodes.bug_intake import BugIntakeNode
    from parrot.flows.dev_loop.nodes.failure_handler import FailureHandlerNode
    from parrot.flows.dev_loop.nodes.intent_classifier import IntentClassifierNode
    from parrot.flows.dev_loop.nodes.research import ResearchNode

    async def intent_exec(self, ctx, deps=None, **kw):
        return self.shared_state(ctx)["bug_brief"]

    async def bug_intake_exec(self, ctx, deps=None, **kw):
        return self.shared_state(ctx)["bug_brief"]

    async def research_exec(self, ctx, deps=None, **kw):
        shared = self.shared_state(ctx)
        out = ResearchOutput(
            jira_issue_key="OPS-1", spec_path="sdd/specs/x.spec.md", feat_id="FEAT-130",
            branch_name="feat-130-fix", worktree_path=".", log_excerpts=[],
        )
        shared["research_output"] = out
        return out

    async def dev_exec(self, ctx, deps=None, **kw):
        shared = self.shared_state(ctx)
        run_id = shared["run_id"]
        await fake.emit_usage(run_id=run_id, node_id=self.name, input_tokens=500, output_tokens=200)
        out = DevelopmentOutput(files_changed=["a.py"], commit_shas=["abc"], summary="ok")
        shared["development_output"] = out
        return out

    async def qa_exec(self, ctx, deps=None, **kw):
        shared = self.shared_state(ctx)
        run_id = shared["run_id"]
        # Burns tokens BEFORE the call fails — proving the report shows
        # both the error and what was spent trying.
        await fake.emit_usage(run_id=run_id, node_id=self.name, input_tokens=900, output_tokens=100)
        await fake.emit_failure(run_id=run_id, node_id=self.name, error_type="TimeoutError")
        raise TimeoutError("scripted QA dispatch timeout")

    async def failure_exec(self, ctx, deps=None, **kw):
        return {"status": "escalated"}

    monkeypatch.setattr(IntentClassifierNode, "execute", intent_exec)
    monkeypatch.setattr(BugIntakeNode, "execute", bug_intake_exec)
    monkeypatch.setattr(ResearchNode, "execute", research_exec)
    monkeypatch.setattr(DevelopmentNode, "execute", dev_exec)
    monkeypatch.setattr(QANode, "execute", qa_exec)
    monkeypatch.setattr(FailureHandlerNode, "execute", failure_exec)


async def test_failed_node_reported_with_usage(monkeypatch, bug_brief):
    """A failed cycle must report its error AND the tokens burned before
    failing — never silently dropped, never a fabricated total.

    ``ClientCallFailedEvent`` structurally carries no token fields at all
    (TASK-2614's contract: the awaited call either succeeds — tokens, no
    error — or fails — error, no tokens; never both on the same event).
    "Tokens burned before failing" is therefore represented at the SEAT
    level: the round that reported usage before the terminal failure still
    contributes to the seat's totals, and the failed cycle's own row
    carries the error without a fabricated token count.
    """
    fake = _ScriptedDispatcher()
    _stub_bug_mode_qa_failure(monkeypatch, fake)

    flow = build_dev_loop_flow(
        dispatcher=fake, jira_toolkit=AsyncMock(), log_toolkits={},
        redis_url="redis://x", publish_flow_events=False,
    )
    runner = DevLoopRunner(flow, dispatcher=fake, redis_url="redis://x")

    await runner.run(bug_brief, run_id="run-fail-1")

    report = _usage_report_from_disk("run-fail-1")
    qa = next(a for a in report.agents if a.seat == "qa")
    assert qa.failures >= 1
    assert qa.input_tokens == 900  # tokens burned before the terminal failure
    failed_cycle = next(c for c in qa.cycles if c.status == "failed")
    assert failed_cycle.error_type == "TimeoutError"

    md = render_usage_markdown(report)
    assert "Failures" in md
    assert "TimeoutError" in md
