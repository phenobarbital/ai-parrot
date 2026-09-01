"""QANode derives an executable criterion when the brief declares none.

Feature-mode and dev-flow runs reach QA with no ``bug_brief`` at all (see
``_NoBugBrief``), so the deterministic gate used to synthesize a pass
without running anything — leaving whatever ``SynthesisNode`` happened to
run as the only test execution of the entire run.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import (
    BugBrief,
    DevelopmentOutput,
    QAReport,
    ResearchOutput,
)
from parrot.flows.dev_loop.models import CodeReviewVerdict, ManualCriterion, ShellCriterion
from parrot.flows.dev_loop.nodes.qa import QANode


@pytest.fixture
def worktree(tmp_path):
    """A worktree with two package test trees and one package without."""
    for pkg in ("ai-parrot", "ai-parrot-tools"):
        (tmp_path / "packages" / pkg / "tests").mkdir(parents=True)
    (tmp_path / "packages" / "ai-parrot-visualizations" / "src").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def ctx(worktree) -> dict:
    """Briefless shared state: no ``bug_brief``, as in feature/dev-flow."""
    return {
        "run_id": "r1",
        "research_output": ResearchOutput(
            jira_issue_key="",
            spec_path="sdd/specs/x.spec.md",
            feat_id="FEAT-488",
            branch_name="feat-488-x",
            worktree_path=str(worktree),
            log_excerpts=[],
        ),
        "development_output": DevelopmentOutput(
            files_changed=[
                "packages/ai-parrot/src/parrot/loaders/base.py",
                "packages/ai-parrot-tools/src/parrot_tools/http.py",
            ],
            commit_shas=["abc123"],
            summary="implemented TASK-2681",
        ),
    }


def _dispatcher(report: QAReport | None = None) -> MagicMock:
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(
        side_effect=[
            CodeReviewVerdict(passed=True),
            report or QAReport(passed=True, criterion_results=[], lint_passed=True),
        ]
    )
    return dispatcher


def _qa_brief(dispatcher: MagicMock):
    """The brief of the deterministic sdd-qa dispatch (the second call)."""
    return dispatcher.dispatch.await_args_list[1].kwargs["brief"]


@pytest.mark.asyncio
async def test_derives_pytest_scoped_to_changed_packages(ctx):
    dispatcher = _dispatcher()

    await QANode(dispatcher=dispatcher).execute(ctx)

    criteria = _qa_brief(dispatcher).acceptance_criteria
    assert len(criteria) == 1
    assert isinstance(criteria[0], ShellCriterion)
    assert criteria[0].command == ("pytest packages/ai-parrot-tools/tests packages/ai-parrot/tests")


@pytest.mark.asyncio
async def test_derived_criterion_gates_the_run(ctx):
    """A failing derived criterion must fail QA, not just be recorded."""
    dispatcher = _dispatcher(QAReport(passed=False, criterion_results=[], lint_passed=True))

    report = await QANode(dispatcher=dispatcher).execute(ctx)

    assert report.passed is False


@pytest.mark.asyncio
async def test_package_without_tests_is_not_a_target(ctx):
    """pytest exits 4 on a missing path — never point it at one."""
    ctx["development_output"] = DevelopmentOutput(
        files_changed=["packages/ai-parrot-visualizations/src/parrot/outputs/x.py"],
        commit_shas=["abc"],
        summary="s",
    )
    dispatcher = _dispatcher()

    await QANode(dispatcher=dispatcher).execute(ctx)

    # Nothing mapped to an existing test tree → unscoped fallback.
    assert _qa_brief(dispatcher).acceptance_criteria[0].command == "pytest"


@pytest.mark.asyncio
async def test_docs_only_change_derives_nothing(ctx, monkeypatch):
    """No Python touched → no pytest run invented, and no dispatch."""
    ctx["development_output"] = DevelopmentOutput(
        files_changed=["docs/features/feat-488.md"],
        commit_shas=["abc"],
        summary="s",
    )
    monkeypatch.setattr(QANode, "_get_changed_files", AsyncMock(return_value=[]))
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[CodeReviewVerdict(passed=True)])

    report = await QANode(dispatcher=dispatcher).execute(ctx)

    assert dispatcher.dispatch.await_count == 1  # code review only
    assert "no executable criteria" in report.lint_output


@pytest.mark.asyncio
async def test_falls_back_to_git_diff_when_development_published_nothing(ctx, monkeypatch):
    ctx["development_output"] = DevelopmentOutput(files_changed=[], commit_shas=[], summary="s")
    monkeypatch.setattr(
        QANode,
        "_get_changed_files",
        AsyncMock(return_value=["packages/ai-parrot/src/parrot/x.py"]),
    )
    dispatcher = _dispatcher()

    await QANode(dispatcher=dispatcher).execute(ctx)

    assert _qa_brief(dispatcher).acceptance_criteria[0].command == "pytest packages/ai-parrot/tests"


@pytest.mark.asyncio
async def test_declared_criteria_are_never_overridden(ctx):
    """A brief that declares its own criteria is left exactly as-is."""
    declared = ShellCriterion(name="acceptance", command="pytest tests/test_one.py")
    ctx["bug_brief"] = BugBrief(
        summary="x" * 20,
        affected_component="y",
        log_sources=[],
        acceptance_criteria=[declared],
        escalation_assignee="a",
        reporter="b",
    )
    dispatcher = _dispatcher()

    await QANode(dispatcher=dispatcher).execute(ctx)

    assert _qa_brief(dispatcher).acceptance_criteria == [declared]


@pytest.mark.asyncio
async def test_manual_only_brief_is_left_alone(ctx):
    """Declaring only manual criteria is a deliberate 'no automated checks'."""
    ctx["bug_brief"] = BugBrief(
        summary="x" * 20,
        affected_component="y",
        log_sources=[],
        acceptance_criteria=[ManualCriterion(name="looks right", text="the chart renders")],
        escalation_assignee="a",
        reporter="b",
    )
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[CodeReviewVerdict(passed=True)])

    await QANode(dispatcher=dispatcher).execute(ctx)

    assert dispatcher.dispatch.await_count == 1  # no deterministic dispatch


def test_pytest_targets_are_deduped_and_sorted(worktree):
    targets = QANode._pytest_targets(
        [
            "packages/ai-parrot-tools/src/a.py",
            "packages/ai-parrot/src/b.py",
            "packages/ai-parrot/src/c.py",
            "scripts/sdd/reserve_ids.py",
        ],
        str(worktree),
    )
    assert targets == ["packages/ai-parrot-tools/tests", "packages/ai-parrot/tests"]
