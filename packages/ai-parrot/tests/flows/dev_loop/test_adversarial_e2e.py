"""End-to-end integration tests for FEAT-375 (Module 7, spec §4).

Covers the cross-module paths per-task unit tests don't exercise together:
a real ``CodexCodeDispatcher`` (fake-process pattern, mirrors
``test_codex_dispatcher.py``) driving a real ``CodexAdversarialReviewDispatcher``
into a real ``QANode`` triage loop, plus the ``ParallelPerspectiveReviewDispatcher``
composite path.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Sequence
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot import conf
from parrot.flows.dev_loop import BugBrief, FlowtaskCriterion, QAReport, ResearchOutput
from parrot.flows.dev_loop.code_review import (
    CodexAdversarialReviewDispatcher,
    ParallelPerspectiveReviewDispatcher,
)
from parrot.flows.dev_loop.dispatcher import CodexCodeDispatcher
from parrot.flows.dev_loop.models import (
    AdversarialFinding,
    CodeReviewFinding,
    CodeReviewVerdict,
    TriageReport,
)
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.session_state import SessionHost


# ---------------------------------------------------------------------------
# Fake-CLI-binary harness (mirrors test_codex_dispatcher.py — no real
# subprocess/network access; `_create_process` is monkeypatched to write a
# canned JSON payload to the `-o` file, exercising the REAL command-building,
# prompt-composition, and output-validation code paths).
# ---------------------------------------------------------------------------


class _AsyncBytesStream:
    def __init__(self, chunks: Sequence[str]) -> None:
        self._chunks = [chunk.encode("utf-8") for chunk in chunks]

    async def readline(self) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    async def read(self) -> bytes:
        data = b"".join(self._chunks)
        self._chunks.clear()
        return data


class _FakeCodexProcess:
    def __init__(self, *, stdout_lines: Sequence[str] = (), stderr: str = "", return_code: int = 0) -> None:
        self.stdout = _AsyncBytesStream(stdout_lines)
        self.stderr = _AsyncBytesStream([stderr])
        self._return_code = return_code

    async def wait(self) -> int:
        return self._return_code

    def kill(self) -> None:
        pass


def _write_output(command: Sequence[str], payload: str) -> None:
    output_path = Path(command[command.index("-o") + 1])
    output_path.write_text(payload, encoding="utf-8")


@pytest.fixture
def codex_dispatcher(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatcher.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    disp = CodexCodeDispatcher(
        max_concurrent=1, redis_url="redis://localhost:6379/0", stream_ttl_seconds=60
    )
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _ensure_redis():
        return fake_redis

    monkeypatch.setattr(disp, "_ensure_redis", _ensure_redis)
    return disp


@pytest.fixture
def ctx(tmp_path):
    return {
        "run_id": "r1",
        "research_output": ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="x",
            feat_id="FEAT-130",
            branch_name="feat-130-fix",
            worktree_path=str(tmp_path),
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


# ---------------------------------------------------------------------------
# Integration tests (spec §4 — names fixed by spec)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_adversarial_review_triage(codex_dispatcher, ctx, monkeypatch):
    """Real CodexAdversarialReviewDispatcher → QANode triage: 1 CONFIRM (rerun), 1 REJECT (notes)."""
    verdict_payload = json.dumps({
        "passed": False,
        "findings": [
            {"message": "Off by one", "severity": "major", "file": "a.py", "line": 10},
            {"message": "Style nit", "severity": "minor", "file": "b.py", "line": 2},
        ],
        "summary": "two findings",
        # Lying stub: the advisory dispatcher must strip this regardless.
        "files_modified": ["should_not_appear.py"],
    })

    async def _fake_create(command: Sequence[str]):
        _write_output(command, verdict_payload)
        return _FakeCodexProcess(stdout_lines=['{"type":"turn.completed"}\n'])

    monkeypatch.setattr(codex_dispatcher, "_create_process", _fake_create)

    adversarial_reviewer = CodexAdversarialReviewDispatcher(dispatcher=codex_dispatcher)

    confirmed = AdversarialFinding(
        message="Off by one", severity="major", file="a.py", line=10,
        source="codex-adversarial", disposition="confirm", triage_reason="fixed the off-by-one",
        finding_id="finding-0",
    )
    rejected = AdversarialFinding(
        message="Style nit", severity="minor", file="b.py", line=2,
        source="codex-adversarial", disposition="reject", triage_reason="not actually an issue",
        finding_id="finding-1",
    )
    triage_report = TriageReport(findings=[confirmed, rejected], files_modified=["a.py"])

    qa_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    rerun_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dev_dispatcher = MagicMock()
    dev_dispatcher.dispatch = AsyncMock(side_effect=[qa_report, triage_report, rerun_report])

    node = QANode(dispatcher=dev_dispatcher, codereview_dispatcher=adversarial_reviewer)
    report = await node.execute(ctx)

    assert report.passed is True
    # deterministic (1) + triage (2) + rerun-after-CONFIRM-fix (3).
    assert dev_dispatcher.dispatch.await_count == 3
    assert "rejected:" in report.notes
    assert "Style nit" in report.notes
    assert "not actually an issue" in report.notes


@pytest.mark.asyncio
async def test_e2e_escalation_opens_gate_and_pr_note(codex_dispatcher, ctx, monkeypatch):
    """ESCALATE → a real SessionHost gate is opened+pending, then resolves; note is PR-visible."""
    verdict_payload = json.dumps({
        "passed": False,
        "findings": [
            {"message": "Possible security issue", "severity": "critical", "file": "auth.py", "line": 5},
        ],
        "summary": "one finding",
    })

    async def _fake_create(command: Sequence[str]):
        _write_output(command, verdict_payload)
        return _FakeCodexProcess(stdout_lines=['{"type":"turn.completed"}\n'])

    monkeypatch.setattr(codex_dispatcher, "_create_process", _fake_create)

    adversarial_reviewer = CodexAdversarialReviewDispatcher(dispatcher=codex_dispatcher)

    escalated = AdversarialFinding(
        message="Possible security issue", severity="critical", file="auth.py", line=5,
        source="codex-adversarial", disposition="escalate", triage_reason="needs a human call",
        finding_id="finding-0",
    )
    triage_report = TriageReport(findings=[escalated], files_modified=[])

    qa_report = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dev_dispatcher = MagicMock()
    dev_dispatcher.dispatch = AsyncMock(side_effect=[qa_report, triage_report])

    session_host = SessionHost(run_id="r1")
    ctx["session_host"] = session_host

    node = QANode(dispatcher=dev_dispatcher, codereview_dispatcher=adversarial_reviewer)
    task = asyncio.create_task(node.execute(ctx))
    # Yield control so execute() runs up through open_gate()+wait_gate() before
    # we inspect state (QANode's ESCALATE path awaits gate resolution, mirroring
    # `_resolve_blocking_manual_criteria` — mirrors the FEAT-322 HITL pattern).
    # Several awaits happen first (deterministic QA dispatch, the real codex
    # dispatch's semaphore/subprocess/stream-reading chain, the triage
    # dispatch) so poll briefly rather than assuming a fixed yield count.
    for _ in range(200):
        if any(
            g.kind == "review_escalation" for g in session_host.state.gates.values()
        ):
            break
        await asyncio.sleep(0)
    else:
        if task.done() and task.exception():
            raise task.exception()
        pytest.fail("review_escalation gate never opened")

    pending_gates = [g for g in session_host.state.gates.values() if g.kind == "review_escalation"]
    assert len(pending_gates) == 1
    assert pending_gates[0].status == "pending"

    session_host.resolve_gate(pending_gates[0].gate_id, "approved", resolved_by="human:reviewer")

    report = await task
    assert "Escalated for human review" in report.notes
    assert "Possible security issue" in report.notes
    # Approved → the escalation no longer blocks code_review_passed.
    assert report.code_review_passed is True


@pytest.mark.asyncio
async def test_e2e_parallel_perspective(monkeypatch):
    """Primary + adversary stubs with one overlapping finding → 1 agreement (both sources) + disjoint; no judge call."""
    monkeypatch.setattr(conf, "DEV_LOOP_CODEREVIEW_JUDGE", False)

    primary_verdict = CodeReviewVerdict(
        passed=False,
        findings=[
            CodeReviewFinding(message="Off by one", severity="major", file="a.py"),
            CodeReviewFinding(message="Only primary sees this", severity="minor", file="c.py"),
        ],
    )
    adversary_verdict = CodeReviewVerdict(
        passed=False,
        findings=[
            CodeReviewFinding(message="off  by one", severity="major", file="a.py"),
            CodeReviewFinding(message="Only adversary sees this", severity="minor", file="d.py"),
        ],
    )

    primary = MagicMock()
    primary.review = AsyncMock(return_value=primary_verdict)
    adversary = MagicMock()
    adversary.review = AsyncMock(return_value=adversary_verdict)

    judge = MagicMock()
    judge.dispatch = AsyncMock()

    dispatcher = ParallelPerspectiveReviewDispatcher(
        primary=primary,
        adversary=adversary,
        judge_dispatcher=judge,
        judge_enabled=conf.DEV_LOOP_CODEREVIEW_JUDGE,
    )
    verdict = await dispatcher.review(brief=None, run_id="r1", node_id="qa", cwd="/tmp")

    assert len(verdict.findings) == 3  # 1 agreement + 2 disjoint findings
    agreements = [f for f in verdict.findings if "," in f.source]
    assert len(agreements) == 1
    assert agreements[0].source == "primary,codex-adversarial"
    disjoint_sources = {f.source for f in verdict.findings if "," not in f.source}
    assert disjoint_sources == {"primary", "codex-adversarial"}
    judge.dispatch.assert_not_called()
