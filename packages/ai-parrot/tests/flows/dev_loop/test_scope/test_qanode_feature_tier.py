"""QANode feature tier via the test-scope kernel (FEAT-563 TASK-3311)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import DevelopmentOutput, QAReport, ResearchOutput
from parrot.flows.dev_loop.models import CriterionResult
from parrot.flows.dev_loop.nodes.qa import QANode


def _research(worktree: Path) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-1",
        branch_name="feat-1-x",
        worktree_path=str(worktree),
        log_excerpts=[],
    )


@pytest.mark.asyncio
async def test_feature_tier_equals_mirror_selection(tmp_path, monkeypatch):
    (tmp_path / "packages/ai-parrot/tests/flows/dev_loop").mkdir(parents=True)
    files = ["packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py"]
    monkeypatch.setattr(QANode, "_get_changed_files", AsyncMock(return_value=[]))

    shared = {"development_output": DevelopmentOutput(files_changed=files, commit_shas=["a"], summary="s")}
    node = QANode(dispatcher=MagicMock())

    criteria = await node._default_criteria(shared, _research(tmp_path))

    got_targets = {
        op for c in criteria for op in c.command.split() if op.startswith(("packages/", "tests/"))
    }
    assert got_targets == set(QANode._pytest_targets(files, str(tmp_path)))


@pytest.mark.asyncio
async def test_empty_feature_plan_derives_no_criterion(tmp_path, monkeypatch):
    (tmp_path / "packages/x/src").mkdir(parents=True)  # no tests dir at all
    monkeypatch.setattr(QANode, "_get_changed_files", AsyncMock(return_value=[]))

    shared = {
        "development_output": DevelopmentOutput(
            files_changed=["packages/x/src/mod.py"], commit_shas=["a"], summary="s"
        )
    }
    node = QANode(dispatcher=MagicMock())

    criteria = await node._default_criteria(shared, _research(tmp_path))

    assert criteria == []


@pytest.mark.asyncio
async def test_qanode_records_green_escalations(tmp_path, monkeypatch):
    import parrot.flows.dev_loop.nodes.qa as qa_mod
    from parrot.flows.dev_loop.test_scope.datatypes import CoreHit, PytestInvocation, ScopePlan, TestTarget

    plan = ScopePlan(
        tier="feature",
        invocations=(
            PytestInvocation(
                distribution="ai-parrot",
                argv=("pytest", "packages/ai-parrot/tests"),
                targets=(TestTarget(path="packages/ai-parrot/tests", distribution="ai-parrot", reason="core"),),
            ),
        ),
        escalated=(),
        notes=(),
        core_hits=(
            CoreHit(
                path="packages/ai-parrot/src/parrot/clients/base.py",
                module="parrot.clients.base",
                fanin=100,
                forced=False,
                distributions=("ai-parrot",),
            ),
        ),
        skipped_escalations=(),
    )
    shared = {"test_scope_plan": plan}
    report = QAReport(
        passed=True,
        criterion_results=[CriterionResult(name="pytest[ai-parrot] (core escalation)", passed=True)],
        lint_passed=True,
    )
    record_mock = MagicMock()
    monkeypatch.setattr(qa_mod, "record_green_escalation", record_mock)

    node = QANode(dispatcher=MagicMock())
    await node._record_green_escalations(shared, _research(tmp_path), report)

    record_mock.assert_called_once_with(
        Path(str(tmp_path)), ["ai-parrot"], ["packages/ai-parrot/src/parrot/clients/base.py"]
    )
