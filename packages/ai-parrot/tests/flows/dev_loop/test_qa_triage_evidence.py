"""Git-verified triage evidence (FEAT-497 Module 1).

Unit tests for `QANode._git_state` / `QANode._paths_touched_since` against a
real git repo, plus integration tests driving `QANode.execute` end to end to
confirm the git-derived evidence set — not the triage worker's claim — is
what gates the deterministic-QA rerun and `_confirm_has_evidence`.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import BugBrief, FlowtaskCriterion, QAReport, ResearchOutput
from parrot.flows.dev_loop.models import AdversarialFinding, CodeReviewVerdict, TriageReport
from parrot.flows.dev_loop.nodes.qa import QANode


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "dev")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "baseline")
    return tmp_path


def _ctx(worktree_path: str) -> dict:
    return {
        "run_id": "r1",
        "research_output": ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="x",
            feat_id="FEAT-130",
            branch_name="feat-130-fix",
            worktree_path=worktree_path,
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


def _advisory_reviewer(verdict: CodeReviewVerdict) -> MagicMock:
    reviewer = MagicMock()
    reviewer.advisory = True
    reviewer.review = AsyncMock(return_value=verdict)
    return reviewer


def _finding(message: str, file: str = "a.py") -> AdversarialFinding:
    return AdversarialFinding(message=message, severity="major", file=file, source="codex-adversarial")


# ---- unit: the helpers -------------------------------------------------


@pytest.mark.asyncio
async def test_git_failure_degrades_to_no_evidence(tmp_path):
    """Non-git worktree_path → [] and no exception."""
    before = await QANode._git_state(str(tmp_path / "nope"))
    assert before == ("", frozenset())
    assert await QANode._paths_touched_since(str(tmp_path / "nope"), before) == []


@pytest.mark.asyncio
async def test_uncommitted_edit_during_triage_counts_as_evidence(repo):
    before = await QANode._git_state(str(repo))
    (repo / "a.py").write_text("x = 2\n")
    assert await QANode._paths_touched_since(str(repo), before) == ["a.py"]


@pytest.mark.asyncio
async def test_git_visible_changes_are_reported_even_if_unclaimed(repo):
    """A commit added during the dispatch is evidence, claim or no claim."""
    before = await QANode._git_state(str(repo))
    (repo / "b.py").write_text("y = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "triage fix")
    assert await QANode._paths_touched_since(str(repo), before) == ["b.py"]


@pytest.mark.asyncio
async def test_pre_existing_dirty_file_is_not_evidence(repo):
    (repo / "a.py").write_text("x = 2\n")  # dirty BEFORE the snapshot
    before = await QANode._git_state(str(repo))
    assert await QANode._paths_touched_since(str(repo), before) == []


# ---- integration: QANode.execute ---------------------------------------


@pytest.mark.asyncio
async def test_claimed_but_invisible_files_are_dropped(repo, caplog):
    """Worker claims 13 paths, git shows none → files_modified [] + WARNING logged."""
    finding = _finding("Off by one")
    verdict = CodeReviewVerdict(passed=False, findings=[finding])
    reviewer = _advisory_reviewer(verdict)

    confirmed = finding.model_copy(
        update={"disposition": "confirm", "triage_reason": "valid, fixed", "finding_id": "finding-0"}
    )
    claimed = [f"phantom_{i}.py" for i in range(13)]
    triage_report = TriageReport(findings=[confirmed], files_modified=claimed)

    qa_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[qa_report, triage_report])

    session_host = MagicMock()
    session_host.open_gate = MagicMock(return_value=("gate-1", MagicMock()))

    async def _wait_gate(gate_id):
        resolved = MagicMock()
        resolved.status = "rejected"
        return resolved

    session_host.wait_gate = AsyncMock(side_effect=_wait_gate)

    ctx = _ctx(str(repo))
    ctx["session_host"] = session_host

    node = QANode(dispatcher=dispatcher, codereview_dispatcher=reviewer)
    with caplog.at_level(logging.WARNING):
        report = await node.execute(ctx)

    # No rerun: git saw nothing change, so files_modified is empty.
    assert dispatcher.dispatch.await_count == 2
    assert any("Triage worker claimed" in message for message in caplog.messages)
    # The unevidenced CONFIRM escalates rather than silently passing.
    assert "Escalated for human review" in report.notes


@pytest.mark.asyncio
async def test_confirm_without_git_evidence_escalates(repo):
    """CONFIRM naming a file git never saw → note contains 'Escalated for human review'."""
    finding = _finding("Off by one")
    verdict = CodeReviewVerdict(passed=False, findings=[finding])
    reviewer = _advisory_reviewer(verdict)

    confirmed = finding.model_copy(
        update={"disposition": "confirm", "triage_reason": "fixed it", "finding_id": "finding-0"}
    )
    triage_report = TriageReport(findings=[confirmed], files_modified=["a.py"])

    qa_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[qa_report, triage_report])

    session_host = MagicMock()
    session_host.open_gate = MagicMock(return_value=("gate-1", MagicMock()))

    async def _wait_gate(gate_id):
        resolved = MagicMock()
        resolved.status = "rejected"
        return resolved

    session_host.wait_gate = AsyncMock(side_effect=_wait_gate)

    ctx = _ctx(str(repo))
    ctx["session_host"] = session_host

    node = QANode(dispatcher=dispatcher, codereview_dispatcher=reviewer)
    report = await node.execute(ctx)

    # `a.py` was claimed but git saw no change during the dispatch — not evidence.
    assert dispatcher.dispatch.await_count == 2
    assert "Escalated for human review" in report.notes


@pytest.mark.asyncio
async def test_triage_claim_without_git_evidence_skips_the_qa_rerun(repo):
    """Triage claims files it never wrote → dispatch awaited 2x (deterministic + triage), not 3x."""
    finding = _finding("Off by one")
    verdict = CodeReviewVerdict(passed=False, findings=[finding])
    reviewer = _advisory_reviewer(verdict)

    confirmed = finding.model_copy(
        update={"disposition": "confirm", "triage_reason": "valid, fixed", "finding_id": "finding-0"}
    )
    triage_report = TriageReport(findings=[confirmed], files_modified=["a.py"])

    qa_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[qa_report, triage_report])

    node = QANode(dispatcher=dispatcher, codereview_dispatcher=reviewer)
    report = await node.execute(_ctx(str(repo)))

    assert dispatcher.dispatch.await_count == 2


@pytest.mark.asyncio
async def test_triage_that_really_commits_triggers_the_rerun(repo):
    """The fake dispatcher's triage side-effect commits a file → dispatch awaited 3x."""
    finding = _finding("Off by one")
    verdict = CodeReviewVerdict(passed=False, findings=[finding])
    reviewer = _advisory_reviewer(verdict)

    confirmed = finding.model_copy(
        update={"disposition": "confirm", "triage_reason": "valid, fixed", "finding_id": "finding-0"}
    )
    triage_report = TriageReport(findings=[confirmed], files_modified=["a.py"])

    qa_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    rerun_report = QAReport(passed=True, criterion_results=[], lint_passed=True)

    async def _dispatch_side_effect(*args, **kwargs):
        call_index = dispatcher.dispatch.await_count - 1
        if call_index == 0:
            return qa_report
        if call_index == 1:
            (repo / "a.py").write_text("x = 2\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "triage fix")
            return triage_report
        return rerun_report

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=_dispatch_side_effect)

    node = QANode(dispatcher=dispatcher, codereview_dispatcher=reviewer)
    report = await node.execute(_ctx(str(repo)))

    assert dispatcher.dispatch.await_count == 3
    assert report.passed is True
    assert "Escalated for human review" not in (report.notes or "")
