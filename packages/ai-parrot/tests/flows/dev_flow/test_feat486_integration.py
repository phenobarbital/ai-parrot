"""FEAT-486 integration tests — the three spec §4 integration rows.

Everything is stubbed: no provider is contacted, no git is run, no Redis
is required. What is NOT stubbed is the machinery under test — the real
``DevelopmentNode``/``DevAgentPool`` wave loop, the real
``RunLedgerRecorder``, the real ``compute_input_fingerprint`` and the real
``ParallelPerspectiveReviewDispatcher`` merge.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan, ReviewPairPlan
from parrot.flows.dev_flow.runner import DevFlowRunner
from parrot.flows.dev_loop.checkpoint import compute_input_fingerprint
from parrot.flows.dev_loop.code_review import (
    CodeReviewDispatcherFactory,
    ParallelPerspectiveReviewDispatcher,
)
from parrot.flows.dev_loop.dispatchers.mantle import (
    MantleAdversarialReviewDispatcher,
)
from parrot.flows.dev_loop.models import (
    CodeReviewFinding,
    CodeReviewVerdict,
    DevAgentSpec,
    DevelopmentOutput,
    FeatureBrief,
    ResearchOutput,
)
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
from parrot.observability.context import current_run_id, current_seat, usage_attribution
from parrot.observability.recorders.models import UsageRecord
from parrot.observability.recorders.run_ledger import RunLedgerRecorder

TWO_SEATS = [
    DevAgentSpec(agent="nova", model="zai.glm-5"),
    DevAgentSpec(agent="nova", model="qwen.qwen3-coder-480b-a35b-v1:0"),
]


def _research(worktree_path: str) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-486",
        spec_path="sdd/specs/refactor-dev-flow.spec.md",
        feat_id="FEAT-486",
        branch_name="feat-486-refactor-dev-flow",
        worktree_path=worktree_path,
        log_excerpts=[],
    )


def _write_index(worktree: Path, tasks: list[dict[str, Any]]) -> None:
    index_dir = worktree / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "refactor-dev-flow.json").write_text(
        json.dumps(
            {
                "feature": "refactor-dev-flow",
                "feature_id": "FEAT-486",
                "tasks": tasks,
            }
        )
    )


class LedgerRecordingDispatcher:
    """Stub dispatcher that attributes usage exactly like the real ones.

    Real dispatchers wrap their client call in
    ``usage_attribution(run_id, seat=node_id)``
    (``dispatchers/llm.py:215``, ``dispatchers/claude.py:797``) and the
    client's ``AfterClientCallEvent`` becomes a ``UsageRecord`` whose
    ``run_id``/``seat`` are read off those ContextVars by the subscriber.
    This double reproduces that contract without a provider: it enters the
    same context manager and records off the same ContextVars.
    """

    def __init__(self, ledger: RunLedgerRecorder, model: str) -> None:
        self._ledger = ledger
        self._model = model
        self.dispatched: list[tuple[str, str]] = []

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, **_kw):
        task_id = getattr(brief, "task_id", "")
        with usage_attribution(run_id, seat=node_id):
            self.dispatched.append((node_id, task_id))
            # `RunLedgerRecorder.record` is a coroutine (AbstractLogger's
            # contract) — awaited INSIDE the attribution block, exactly as
            # the real UsageRecordingSubscriber fan-out does.
            await self._ledger.record(
                UsageRecord(
                    provider="aws.bedrock",
                    client_name="bedrock-mantle",
                    model=self._model,
                    input_tokens=100,
                    output_tokens=50,
                    usage_reported=True,
                    run_id=current_run_id.get(),
                    seat=current_seat.get(),
                    node_id=current_seat.get(),
                )
            )
        return DevelopmentOutput(
            files_changed=[f"{task_id}.py"],
            commit_shas=[f"sha-{task_id}"],
            summary=task_id,
        )


@pytest.mark.asyncio
class TestMultiAgentEndToEnd:
    """Spec §4: ``test_dev_flow_multi_agent_end_to_end``."""

    async def test_dev_flow_multi_agent_end_to_end(self, tmp_path, caplog):
        _write_index(
            tmp_path,
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
            ],
        )
        ledger = RunLedgerRecorder(run_id="run-486")
        built: list[LedgerRecordingDispatcher] = []

        def _builder(spec: DevAgentSpec):
            dispatcher = LedgerRecordingDispatcher(ledger, spec.model)
            built.append(dispatcher)
            return dispatcher, object()

        plan = DevFlowModelPlan(dev_pool=TWO_SEATS)
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=plan.to_pool_config(),
            dispatcher_builder=_builder,
        )

        with caplog.at_level(logging.INFO):
            result = await node.execute(
                {"run_id": "run-486", "research_output": _research(str(tmp_path))}
            )

        # 1. Both configured workers were materialized and dispatched to.
        assert len(built) == 2
        assert sorted(t for d in built for _n, t in d.dispatched) == ["TASK-1", "TASK-2"]
        assert set(result.files_changed) == {"TASK-1.py", "TASK-2.py"}
        assert result.incomplete_tasks == []

        # 2. The FEAT-486 deployment log names every worker's backend:model.
        assert "Deploying 2 dev sub-agent(s)" in caplog.text
        assert "w1=nova:zai.glm-5" in caplog.text
        assert "w2=nova:qwen.qwen3-coder-480b-a35b-v1:0" in caplog.text

        # 3. FEAT-479: per-seat attribution reached the run ledger.
        seats = {usage.seat for usage in ledger.by_seat()}
        assert {"development.w1", "development.w2"} <= seats
        for usage in ledger.by_seat():
            if usage.seat in ("development.w1", "development.w2"):
                assert usage.node_id == usage.seat

    async def test_single_task_index_collapses_the_same_plan(self, tmp_path, caplog):
        """The same 2-seat plan deploys ONE agent for a 1-task feature."""
        _write_index(tmp_path, [{"id": "TASK-1", "status": "pending", "depends_on": []}])
        ledger = RunLedgerRecorder(run_id="run-486")
        built: list[LedgerRecordingDispatcher] = []

        def _builder(spec: DevAgentSpec):
            dispatcher = LedgerRecordingDispatcher(ledger, spec.model)
            built.append(dispatcher)
            return dispatcher, object()

        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevFlowModelPlan(dev_pool=TWO_SEATS).to_pool_config(),
            dispatcher_builder=_builder,
        )
        with caplog.at_level(logging.INFO):
            await node.execute(
                {"run_id": "run-486", "research_output": _research(str(tmp_path))}
            )

        assert len(built) == 1
        assert "collapsing" in caplog.text
        assert {u.seat for u in ledger.by_seat()} == {"development.w1"}


class TestCheckpointResumeWithPlan:
    """Spec §4: ``test_dev_flow_checkpoint_resume_with_plan``."""

    @staticmethod
    def _policy(**flow_kwargs: Any) -> dict[str, Any]:
        runner = DevFlowRunner.__new__(DevFlowRunner)
        runner._dev_loop_flow_kwargs = flow_kwargs
        return runner._execution_policy_for_fingerprint()

    @staticmethod
    def _brief() -> FeatureBrief:
        return FeatureBrief(
            document_path="sdd/specs/refactor-dev-flow.spec.md",
            document_kind="spec",
        )

    def _fingerprint(self, **flow_kwargs: Any) -> str:
        return compute_input_fingerprint(
            workflow="dev-flow",
            brief=self._brief(),
            repository="/repo",
            execution_policy=self._policy(**flow_kwargs),
            document_identity="sdd/specs/refactor-dev-flow.spec.md",
        )

    def test_same_plan_resumes_to_the_same_fingerprint(self):
        """Resume with an unchanged plan ⇒ hit."""
        first = self._fingerprint(model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS))
        second = self._fingerprint(model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS))
        assert first == second

    def test_changed_routing_field_misses(self):
        """A different pool shape ⇒ deliberate mismatch ⇒ fresh run."""
        two = self._fingerprint(model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS))
        one = self._fingerprint(model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS[:1]))
        assert two != one

    def test_changed_review_backend_misses(self):
        base = self._fingerprint(model_plan=DevFlowModelPlan())
        other = self._fingerprint(
            model_plan=DevFlowModelPlan(
                review=ReviewPairPlan(primary=DevAgentSpec(agent="codex"))
            )
        )
        assert base != other

    def test_model_only_change_still_hits(self):
        """Swapping a pure model string must NOT force a fresh run."""
        base = self._fingerprint(model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS))
        swapped = self._fingerprint(
            model_plan=DevFlowModelPlan(
                research_primary="claude-sonnet-4-6",
                dev_pool=[
                    DevAgentSpec(agent="nova", model="other-a"),
                    DevAgentSpec(agent="nova", model="other-b"),
                ],
                review=ReviewPairPlan(counter_model="nova-2-lite"),
            )
        )
        assert base == swapped

    def test_no_plan_fingerprint_is_unchanged_from_pre_feat486(self):
        """Omitting the plan must not move existing deployments' digests."""
        legacy_policy = {
            "skip_qa": False,
            "require_plan_approval": False,
            "development_pool_max": 4,
            "ideation_max_rounds": None,
        }
        legacy = compute_input_fingerprint(
            workflow="dev-flow",
            brief=self._brief(),
            repository="/repo",
            execution_policy=legacy_policy,
            document_identity="sdd/specs/refactor-dev-flow.spec.md",
        )
        assert legacy == self._fingerprint(skip_qa=False)

    def test_topology_version_not_bumped(self):
        from parrot.flows.dev_loop.checkpoint import TOPOLOGY_VERSION

        assert TOPOLOGY_VERSION == "1"

    def test_shared_data_allowlist_untouched(self):
        from parrot.flows.dev_loop.checkpoint import _SHARED_DATA_ALLOWLIST

        assert set(_SHARED_DATA_ALLOWLIST) == {
            "bug_brief",
            "bug_findings",
            "research_output",
            "planner_output",
            "development_output",
            "dev_brief",
            "feature_brief",
            "ideation_output",
        }


class _StubPrimaryReviewer:
    """Write-enabled primary reviewer double."""

    agent_name = "claude-code"
    advisory = False

    def __init__(self, verdict: CodeReviewVerdict) -> None:
        self._verdict = verdict
        self.calls = 0

    async def review(self, **_kwargs: Any) -> CodeReviewVerdict:
        self.calls += 1
        return self._verdict


class _FakeMantleClient:
    def __init__(self, verdict: CodeReviewVerdict) -> None:
        self._verdict = verdict
        self.calls: list[dict[str, Any]] = []
        self._events_registry = None

    async def ask(self, prompt: str, **kwargs: Any):
        self.calls.append({"prompt": prompt, **kwargs})
        return type("AIMessage", (), {"structured_output": self._verdict})()


@pytest.mark.asyncio
class TestReviewPairEndToEnd:
    """Spec §4: ``test_dev_flow_review_pair_end_to_end``."""

    @staticmethod
    def _pair(primary_verdict, adversary_verdict):
        client = _FakeMantleClient(adversary_verdict)
        adversary = MantleAdversarialReviewDispatcher(client=client)

        async def _no_git(_cwd, _profile):
            return "diff --git a/x b/x\n+line\n"

        adversary._collect_diff = _no_git
        primary = _StubPrimaryReviewer(primary_verdict)
        pair = CodeReviewDispatcherFactory.create(
            "parallel", primary=primary, adversary=adversary
        )
        return pair, primary, adversary, client

    async def test_qa_path_invokes_both_seats(self):
        pair, primary, _adversary, client = self._pair(
            CodeReviewVerdict(passed=True, findings=[], files_modified=["src/fixed.py"]),
            CodeReviewVerdict(passed=True, findings=[]),
        )
        assert isinstance(pair, ParallelPerspectiveReviewDispatcher)
        await pair.review(
            brief=_research("/tmp/wt"), run_id="run-486", node_id="qa", cwd="/tmp/wt"
        )
        assert primary.calls == 1
        assert len(client.calls) == 1

    async def test_adversary_verdict_is_merged(self):
        pair, _primary, _adversary, _client = self._pair(
            CodeReviewVerdict(passed=True, findings=[]),
            CodeReviewVerdict(
                passed=False,
                findings=[
                    CodeReviewFinding(
                        message="unbounded retry loop", severity="major"
                    )
                ],
            ),
        )
        verdict = await pair.review(
            brief=_research("/tmp/wt"), run_id="run-486", node_id="qa", cwd="/tmp/wt"
        )
        # `passed` is the AND of both sides — the adversary can veto.
        assert verdict.passed is False
        assert any("unbounded retry loop" in f.message for f in verdict.findings)

    async def test_adversary_contributes_no_writes(self):
        """files_modified is always the primary's; the adversary has no tools."""
        pair, _primary, _adversary, client = self._pair(
            CodeReviewVerdict(passed=True, findings=[], files_modified=["src/fixed.py"]),
            CodeReviewVerdict(
                passed=True, findings=[], files_modified=["src/adversary_lied.py"]
            ),
        )
        verdict = await pair.review(
            brief=_research("/tmp/wt"), run_id="run-486", node_id="qa", cwd="/tmp/wt"
        )
        assert verdict.files_modified == ["src/fixed.py"]
        assert "src/adversary_lied.py" not in verdict.files_modified
        # And the adversary was never given tools in the first place.
        assert client.calls[0]["use_tools"] is False
        assert "tools" not in client.calls[0]

    async def test_adversary_outage_does_not_fail_the_gate(self):
        """A Mantle outage degrades; the primary's verdict still stands."""
        client = _FakeMantleClient(None)

        async def _boom(*_a, **_kw):
            raise RuntimeError("401 Unauthorized")

        client.ask = _boom
        adversary = MantleAdversarialReviewDispatcher(client=client)

        async def _no_git(_cwd, _profile):
            return "diff"

        adversary._collect_diff = _no_git
        pair = CodeReviewDispatcherFactory.create(
            "parallel",
            primary=_StubPrimaryReviewer(CodeReviewVerdict(passed=True, findings=[])),
            adversary=adversary,
        )
        verdict = await pair.review(
            brief=_research("/tmp/wt"), run_id="run-486", node_id="qa", cwd="/tmp/wt"
        )
        assert verdict.passed is True
