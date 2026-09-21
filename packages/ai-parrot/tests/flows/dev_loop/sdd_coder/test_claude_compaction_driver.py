"""Regression scenarios for the main-loop Claude receipt reader."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from parrot.flows.dev_loop.sdd_coder import claude_compaction_driver as driver_module
from parrot.flows.dev_loop.sdd_coder.claude_compaction_driver import ClaudeMainLoopCompactionDriver
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import EvidenceRef, ReviewCheckpoint

_EXECUTION_ID = "11111111-1111-4111-8111-111111111111"


def _evidence_ref(artifact_id: str) -> EvidenceRef:
    """Create a minimal evidence reference with a matching digest."""
    content = b"{}"
    return EvidenceRef(
        artifact_id=artifact_id,
        sha256=hashlib.sha256(content).hexdigest(),
        relative_path=f"artifacts/{artifact_id}.json",
        size_bytes=len(content),
        media_type="application/json",
    )


def _checkpoint(*, context_id: str = "main") -> ReviewCheckpoint:
    """Build a valid checkpoint representing the concrete driver context."""
    fields: dict[str, object] = {
        "feature": "sdd-execution-optimization",
        "execution_id": _EXECUTION_ID,
        "worktree": "/tmp/worktree",
        "branch": "feat-FEAT-584-sdd-execution-optimization",
        "base_sha": "a" * 40,
        "implementation_head": "b" * 40,
        "spec_hash": "c" * 64,
        "index_hash": "d" * 64,
        "convention_hashes": {"AGENTS.md": "e" * 64},
        "task_refs": [_evidence_ref("task")],
        "criteria_refs": [_evidence_ref("criteria")],
        "commits": ["a" * 40],
        "validation_refs": [_evidence_ref("validation")],
        "evidence_refs": [_evidence_ref("evidence")],
        "user_constraints": [],
        "pending_actions": [],
        "settlement_ref": _evidence_ref("settlement"),
        "neutral_brief": "Review the implementation.",
        "context_id": context_id,
    }
    checkpoint_id = ReviewCheckpoint.compute_checkpoint_id(**fields)
    return ReviewCheckpoint(checkpoint_id=checkpoint_id, **fields)


def test_supports_gates_on_context_and_per_worktree_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only main is supported and each call evaluates its bound worktree anew."""
    store = ExecutionEvidenceStore(tmp_path / "durable")
    driver = ClaudeMainLoopCompactionDriver(worktree_root=tmp_path / "first", store=store)
    roots: list[Path] = []

    def _status(root: Path) -> dict[str, bool]:
        roots.append(root)
        return {"compaction_plugin": True, "compaction_function_hooks": True, "compaction_api_key": len(roots) == 1}

    monkeypatch.setattr(driver_module, "compaction_status", _status)
    assert not asyncio.run(driver.supports("fork"))
    assert asyncio.run(driver.supports("main"))
    assert not asyncio.run(driver.supports("main"))
    assert roots == [tmp_path / "first", tmp_path / "first"]


def test_compact_emits_requested_and_finished_events(tmp_path: Path) -> None:
    """The explicit failed observation is preceded by both durable marker events."""
    store = ExecutionEvidenceStore(tmp_path / "durable")
    checkpoint = _checkpoint()
    driver = ClaudeMainLoopCompactionDriver(worktree_root=tmp_path / "worktree", store=store)

    receipt = asyncio.run(driver.compact(checkpoint))

    events_path = tmp_path / "durable" / "executions" / _EXECUTION_ID / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert [event["kind"] for event in events] == ["compaction.requested", "compaction.finished"]
    assert receipt.status == "failed"


def test_honest_failed_never_inferred_completed(tmp_path: Path) -> None:
    """No observable receipt returns failed/unknown rather than fabricated completion."""
    store = ExecutionEvidenceStore(tmp_path / "durable")
    checkpoint = _checkpoint()
    driver = ClaudeMainLoopCompactionDriver(worktree_root=tmp_path / "worktree", store=store)

    receipt = asyncio.run(driver.compact(checkpoint))

    assert receipt.status == "failed"
    assert receipt.backend == "unknown"
    assert "No observable Claude Code plugin receipt surface" in receipt.reason
