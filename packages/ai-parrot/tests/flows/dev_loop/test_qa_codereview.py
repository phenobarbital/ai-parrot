"""QANode additive code-review gate (FEAT-250 TASK-008, extended FEAT-270)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import (
    BugBrief,
    FlowtaskCriterion,
    QAReport,
    ResearchOutput,
)
from parrot.flows.dev_loop.models import CodeReviewFinding, CodeReviewVerdict
from parrot.flows.dev_loop.nodes.qa import QANode


@pytest.fixture
def ctx() -> dict:
    return {
        "run_id": "r1",
        "research_output": ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="x",
            feat_id="FEAT-130",
            branch_name="feat-130-fix",
            worktree_path="/abs/.claude/worktrees/feat-130-fix",
        ),
        "bug_brief": BugBrief(
            summary="x" * 20,
            affected_component="y",
            log_sources=[],
            acceptance_criteria=[FlowtaskCriterion(name="run", task_path="a.yaml")],
            escalation_assignee="a",
            reporter="b",
        ),
    }


def _dispatcher(qa_report, verdict_or_exc):
    """Backward-compat dispatcher double.

    QANode's default (no ``codereview_dispatcher`` supplied) wraps this same
    dispatcher in a ``ClaudeCodeReviewDispatcher``, so ``dispatch()`` is
    called twice: first for the code-review pass (so reviewer fixes land
    before verification), then for the deterministic ``sdd-qa`` pass.
    """
    d = MagicMock()
    d.dispatch = AsyncMock(side_effect=[verdict_or_exc, qa_report])
    return d


@pytest.mark.asyncio
async def test_qa_codereview_gate_blocks_on_fail(ctx):
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    verdict = CodeReviewVerdict(
        passed=False,
        findings=[CodeReviewFinding(message="AC not met", severity="major")],
        summary="nope",
    )
    node = QANode(dispatcher=_dispatcher(qa, verdict))
    report = await node.execute(ctx)
    assert report.passed is False
    assert report.code_review_passed is False
    assert report.code_review_findings == ["AC not met"]


@pytest.mark.asyncio
async def test_qa_codereview_passes_when_both_pass(ctx):
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    verdict = CodeReviewVerdict(passed=True, findings=[])
    node = QANode(dispatcher=_dispatcher(qa, verdict))
    report = await node.execute(ctx)
    assert report.passed is True
    assert report.code_review_passed is True
    assert report.code_review_findings == []


@pytest.mark.asyncio
async def test_deterministic_fail_keeps_run_failed(ctx):
    qa = QAReport(passed=False, criterion_results=[], lint_passed=False)
    verdict = CodeReviewVerdict(passed=True, findings=[])
    node = QANode(dispatcher=_dispatcher(qa, verdict))
    report = await node.execute(ctx)
    # Deterministic gate already failed → overall fail even if review passes.
    assert report.passed is False
    assert report.code_review_passed is True


@pytest.mark.asyncio
async def test_qa_codereview_dispatch_is_write_enabled(ctx):
    """FEAT-270: the default reviewer profile is write-enabled (not read-only)."""
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    verdict = CodeReviewVerdict(passed=True, findings=[])
    node = QANode(dispatcher=_dispatcher(qa, verdict))
    await node.execute(ctx)
    # The FIRST dispatch is the code-review gate (reviewer runs before QA).
    cr_profile = node._dispatcher.dispatch.await_args_list[0].kwargs["profile"]
    assert cr_profile.subagent == "sdd-codereview"
    assert cr_profile.permission_mode == "default"
    assert "Edit" in cr_profile.allowed_tools
    assert "Write" in cr_profile.allowed_tools


@pytest.mark.asyncio
async def test_codereview_dispatch_error_does_not_block(ctx):
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    node = QANode(dispatcher=_dispatcher(qa, RuntimeError("infra down")))
    report = await node.execute(ctx)  # must not raise
    assert report.passed is True
    assert report.code_review_passed is True
    assert any("could not run" in f for f in report.code_review_findings)


@pytest.mark.asyncio
async def test_codereview_cwd_uses_worktree_path(ctx):
    ctx["research_output"] = ctx["research_output"].model_copy(
        update={"repo_path": "/abs/.claude/worktrees/repos/r1/nav"}
    )
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    verdict = CodeReviewVerdict(passed=True, findings=[])
    node = QANode(dispatcher=_dispatcher(qa, verdict))
    await node.execute(ctx)
    cr_cwd = node._dispatcher.dispatch.await_args_list[0].kwargs["cwd"]
    assert cr_cwd == ctx["research_output"].worktree_path


@pytest.mark.asyncio
async def test_qa_validates_after_fix(ctx):
    """When reviewer fixes files, QA validates the final state (FEAT-270).

    Write-enabled reviewers run FIRST so their fixes land before the single
    deterministic QA pass — no redundant re-run needed.
    """
    verdict = CodeReviewVerdict(
        passed=True, findings=[], files_modified=["sync.py"]
    )
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[verdict, qa])
    node = QANode(dispatcher=dispatcher)
    report = await node.execute(ctx)
    assert report.passed is True
    assert dispatcher.dispatch.await_count == 2


@pytest.mark.asyncio
async def test_no_fixes_still_two_dispatches(ctx):
    """When reviewer passes with no fixes, same dispatch count (FEAT-270)."""
    verdict = CodeReviewVerdict(passed=True, findings=[], files_modified=[])
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[verdict, qa])
    node = QANode(dispatcher=dispatcher)
    report = await node.execute(ctx)
    assert report.passed is True
    assert dispatcher.dispatch.await_count == 2


@pytest.mark.asyncio
async def test_qa_fails_after_fix(ctx):
    """When QA fails after reviewer fix, overall QA fails (FEAT-270)."""
    verdict = CodeReviewVerdict(
        passed=True, findings=[], files_modified=["sync.py"]
    )
    qa_fail = QAReport(passed=False, criterion_results=[], lint_passed=False)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[verdict, qa_fail])
    node = QANode(dispatcher=dispatcher)
    report = await node.execute(ctx)
    assert report.passed is False


@pytest.mark.asyncio
async def test_backward_compat_no_reviewer(ctx):
    """QANode without codereview_dispatcher auto-creates Claude reviewer."""
    node = QANode(dispatcher=MagicMock())
    assert hasattr(node, "_codereview_dispatcher")


@pytest.mark.asyncio
async def test_custom_codereview_dispatcher_used(ctx):
    """An explicit codereview_dispatcher is used instead of the default."""
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=qa)
    mock_reviewer = MagicMock()
    mock_reviewer.advisory = False
    mock_reviewer.review = AsyncMock(
        return_value=CodeReviewVerdict(passed=True, findings=[])
    )
    node = QANode(dispatcher=dispatcher, codereview_dispatcher=mock_reviewer)
    report = await node.execute(ctx)
    assert report.passed is True
    mock_reviewer.review.assert_awaited_once()
    # Only the deterministic pass goes through the plain dispatcher.
    dispatcher.dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_review_brief_carries_deterministic_qa_results(ctx):
    """The review brief embeds the deterministic gate's recorded results.

    Read-only reviewers (codex adversarial, FEAT-375) cannot execute
    anything that writes — pytest dies on tempdir creation in a read-only
    sandbox — so the brief must carry the already-executed criterion
    results as the evidence to judge from.
    """
    from parrot.flows.dev_loop.models import CriterionResult

    qa = QAReport(
        passed=True,
        criterion_results=[
            CriterionResult(
                name="run",
                kind="flowtask",
                exit_code=0,
                duration_seconds=0.1,
                passed=True,
            )
        ],
        lint_passed=True,
    )
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=qa)
    reviewer = MagicMock()
    reviewer.review = AsyncMock(
        return_value=CodeReviewVerdict(passed=True, findings=[])
    )
    node = QANode(dispatcher=dispatcher, codereview_dispatcher=reviewer)
    await node.execute(ctx)
    review_brief = reviewer.review.await_args.kwargs["brief"]
    assert review_brief.qa_criterion_results == [
        {"name": "run", "kind": "flowtask", "exit_code": 0, "passed": True}
    ]
    assert review_brief.qa_lint_passed is True


@pytest.mark.asyncio
async def test_advisory_review_runs_after_qa_not_concurrently(ctx):
    """Order is the guarantee, not an incidental scheduling detail.

    An advisory reviewer runs read-only and cannot execute a criterion
    itself, so it must see the deterministic gate's recorded results.
    Running the two concurrently withholds that evidence structurally —
    the regression this pins against (bf2693e20 undoing df9f21053).
    """
    calls: list[str] = []

    async def _qa_dispatch(**kwargs):
        calls.append("qa")
        return QAReport(passed=True, criterion_results=[], lint_passed=True)

    async def _review(**kwargs):
        calls.append("review")
        assert "qa" in calls, "review must not start before QA has recorded its results"
        return CodeReviewVerdict(passed=True, findings=[])

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=_qa_dispatch)
    reviewer = MagicMock()
    reviewer.advisory = True
    reviewer.review = AsyncMock(side_effect=_review)

    await QANode(dispatcher=dispatcher, codereview_dispatcher=reviewer).execute(ctx)

    assert calls == ["qa", "review"]


class TestPerRunJudgePanel:
    """``FeatureBrief.judge_panel`` must actually reach the reviewer.

    The field existed, the server parsed it into the brief, and nothing
    ever read it: QANode's reviewer came exclusively from the dispatcher
    injected at construction time, built once at server start from
    ``DEV_LOOP_JUDGE_PANEL`` / ``default_judge_panel()``. Editing the
    panel in the console therefore changed nothing about the run — which
    is how a Gemini judge kept being dispatched after it had been removed
    there.
    """

    class _Panel:
        """Stand-in exposing only the ``with_judges`` seam QANode uses."""

        agent_name = "judge-panel"
        advisory = True

        def __init__(self, judges=None):
            self.judges = judges
            self.calls = []

        def with_judges(self, judges):
            self.calls.append(judges)
            return type(self)(judges)

    def test_brief_panel_overrides_the_injected_panel(self):
        from parrot.flows.dev_loop.models import JudgePanelConfig, JudgeSpec

        panel = self._Panel()
        node = QANode(dispatcher=MagicMock(), codereview_dispatcher=panel)
        judges = [JudgeSpec(agent="claude-code"), JudgeSpec(agent="codex")]
        shared = {"feature_brief": MagicMock(judge_panel=JudgePanelConfig(judges=judges))}

        reviewer = node._active_reviewer(shared)

        assert reviewer is not panel
        assert panel.calls == [judges]

    def test_resolution_is_cached_per_run(self):
        """`execute()` resolves twice (advisory branch + the review itself).

        Both must see the SAME reviewer, and the panel must not be rebuilt
        once per QA attempt.
        """
        from parrot.flows.dev_loop.models import JudgePanelConfig, JudgeSpec

        panel = self._Panel()
        node = QANode(dispatcher=MagicMock(), codereview_dispatcher=panel)
        shared = {
            "feature_brief": MagicMock(
                judge_panel=JudgePanelConfig(judges=[JudgeSpec(agent="codex")])
            )
        }

        first = node._active_reviewer(shared)
        second = node._active_reviewer(shared)

        assert first is second
        assert len(panel.calls) == 1

    def test_no_brief_keeps_the_injected_reviewer(self):
        """Bug-mode runs carry no FeatureBrief at all."""
        panel = self._Panel()
        node = QANode(dispatcher=MagicMock(), codereview_dispatcher=panel)

        assert node._active_reviewer({}) is panel

    def test_empty_panel_keeps_the_injected_reviewer(self):
        node_panel = self._Panel()
        node = QANode(dispatcher=MagicMock(), codereview_dispatcher=node_panel)
        shared = {"feature_brief": MagicMock(judge_panel=None)}

        assert node._active_reviewer(shared) is node_panel

    def test_non_panel_reviewer_is_left_alone(self, caplog):
        """A deployment that swapped the panel out keeps its reviewer.

        DEV_FLOW_USE_REVIEW_PAIR installs the model plan's primary+counter
        pair, which has no ``with_judges``. The override is dropped — but
        loudly, not silently.
        """
        import logging

        from parrot.flows.dev_loop.models import JudgePanelConfig, JudgeSpec

        reviewer = MagicMock(spec=["review", "advisory", "agent_name"])
        reviewer.agent_name = "parallel"
        node = QANode(dispatcher=MagicMock(), codereview_dispatcher=reviewer)
        shared = {
            "feature_brief": MagicMock(
                judge_panel=JudgePanelConfig(judges=[JudgeSpec(agent="codex")])
            )
        }

        with caplog.at_level(logging.WARNING):
            assert node._active_reviewer(shared) is reviewer
        assert "override ignored" in caplog.text
