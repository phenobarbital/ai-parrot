"""Focused tests for the separate dev-loop E2E stage (FEAT-581 M7)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import parrot.flows.dev_loop.nodes.e2e as e2e_module
from parrot.flows.dev_loop import BugBrief, FlowtaskCriterion, QAReport, ResearchOutput
from parrot.flows.dev_loop.models import CodeReviewVerdict
from parrot.flows.dev_loop.nodes.qa import QANode


class _Process:
    """Minimal subprocess double with the asyncio process contract used here."""

    def __init__(self, stdout: bytes, stderr: bytes, returncode: int) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        """Return the configured process output."""
        return self._stdout, self._stderr


def _write_spec(worktree: Path, policy: str) -> Path:
    """Write a minimal spec with a feature E2E policy."""
    path = worktree / "sdd" / "specs" / "feature.spec.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\ne2e:\n  policy: {policy}\n---\n# Feature\n", encoding="utf-8")
    return path.relative_to(worktree)


@pytest.mark.asyncio
async def test_optional_no_plan_skips_without_server_invocation(tmp_path, monkeypatch) -> None:
    """Legacy/optional features remain usable when no E2E plan was generated."""
    spec_path = _write_spec(tmp_path, "optional")
    spawn = AsyncMock()
    monkeypatch.setattr(e2e_module.asyncio, "create_subprocess_exec", spawn)

    result = await e2e_module.run_e2e_stage(worktree=tmp_path, spec_path=spec_path, feature_id="FEAT-1")

    assert result["status"] == "SKIPPED"
    assert result["gate_satisfied"] is True
    spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_required_missing_plan_blocks(tmp_path) -> None:
    """Required policy fails closed before attempting an unavailable plan."""
    spec_path = _write_spec(tmp_path, "required")

    result = await e2e_module.run_e2e_stage(worktree=tmp_path, spec_path=spec_path, feature_id="FEAT-1")

    assert result["status"] == "BLOCKED"
    assert result["gate_satisfied"] is False


@pytest.mark.asyncio
async def test_cli_verdict_is_recorded_with_bounded_argv(tmp_path, monkeypatch) -> None:
    """The stage invokes only the fixed CLI argv and retains its JSON verdict."""
    spec_path = _write_spec(tmp_path, "required")
    plan = tmp_path / "sdd" / "state" / "FEAT-1" / "e2e-plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\n---\n", encoding="utf-8")
    spawn = AsyncMock(return_value=_Process(b'{"status":"PASS","gate_satisfied":true}', b"", 0))
    monkeypatch.setattr(e2e_module.asyncio, "create_subprocess_exec", spawn)

    result = await e2e_module.run_e2e_stage(worktree=tmp_path, spec_path=spec_path, feature_id="FEAT-1")

    assert result["gate_satisfied"] is True
    assert result["verdict"]["status"] == "PASS"
    assert spawn.await_args.args == ("parrot", "e2e", "run", "--plan", "sdd/state/FEAT-1/e2e-plan.md")
    assert spawn.await_args.kwargs["cwd"] == str(tmp_path)


@pytest.mark.asyncio
async def test_optional_failure_is_advisory_in_qa_report(tmp_path, monkeypatch) -> None:
    """A failed optional E2E result remains visible but does not fail QA."""
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.qa.run_e2e_stage",
        AsyncMock(return_value={"policy": "optional", "required": False, "status": "FAIL", "gate_satisfied": False}),
    )
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(
        side_effect=[CodeReviewVerdict(passed=True), QAReport(passed=True, criterion_results=[], lint_passed=True)]
    )
    context = {
        "run_id": "run-1",
        "research_output": ResearchOutput(
            jira_issue_key="",
            spec_path="sdd/specs/feature.spec.md",
            feat_id="FEAT-1",
            branch_name="feature",
            worktree_path=str(tmp_path),
            log_excerpts=[],
        ),
        "bug_brief": BugBrief(
            summary="feature change",
            affected_component="dev-loop",
            log_sources=[],
            acceptance_criteria=[FlowtaskCriterion(name="criterion", task_path="task.yaml")],
            escalation_assignee="owner",
            reporter="reporter",
        ),
    }

    report = await QANode(dispatcher=dispatcher).execute(context)

    assert report.passed is True
    assert context["e2e_result"]["status"] == "FAIL"
    assert "E2E stage: policy=optional status=FAIL" in report.notes


@pytest.mark.asyncio
async def test_required_failure_blocks_qa_report(tmp_path, monkeypatch) -> None:
    """The final QA pass is conjoined with required E2E gate satisfaction."""
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.qa.run_e2e_stage",
        AsyncMock(return_value={"policy": "required", "required": True, "status": "FAIL", "gate_satisfied": False}),
    )
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(
        side_effect=[CodeReviewVerdict(passed=True), QAReport(passed=True, criterion_results=[], lint_passed=True)]
    )
    context = {
        "run_id": "run-1",
        "research_output": ResearchOutput(
            jira_issue_key="",
            spec_path="sdd/specs/feature.spec.md",
            feat_id="FEAT-1",
            branch_name="feature",
            worktree_path=str(tmp_path),
            log_excerpts=[],
        ),
        "bug_brief": BugBrief(
            summary="feature change",
            affected_component="dev-loop",
            log_sources=[],
            acceptance_criteria=[FlowtaskCriterion(name="criterion", task_path="task.yaml")],
            escalation_assignee="owner",
            reporter="reporter",
        ),
    }

    report = await QANode(dispatcher=dispatcher).execute(context)

    assert report.passed is False
    assert context["e2e_result"]["status"] == "FAIL"
