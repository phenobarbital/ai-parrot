"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from parrot.flows.dev_loop.sdd_coder.checkpoint import (
    CheckpointBusyError,
    CheckpointStaleError,
    prepare_review_checkpoint,
    validate_review_checkpoint,
)
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import BackgroundRegistration
from parrot.flows.dev_loop.sdd_coder.models import ExecutionSnapshot
from parrot.flows.dev_loop.sdd_coder.background import BackgroundRegistry

EXECUTION_ID = "33333333-3333-4333-8333-333333333333"
FEATURE_SLUG = "checkpoint-demo"
FEATURE_ID = "FEAT-9101"
BASE_BRANCH = "dev"
FEATURE_BRANCH = "feat-branch"

_CONVENTION_FILES = (
    ".claude/rules/codebase-conventions.md",
    ".agent/rules/codebase-conventions.md",
    "packages/ai-parrot/src/parrot/flows/_rules_data/codebase-conventions.md",
)


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _build_repo(tmp_path: Path) -> Path:
    """A real, tiny git repo standing in for a feature worktree.

    Layout: per-spec index + spec + three convention files + one 'done' task
    (with an Acceptance Criteria section) + one 'pending' task, all in ONE
    commit; a same-tip `origin/<base_branch>` ref stands in for the remote
    the worktree was forked from (a locally-named branch resolves through
    `git rev-parse origin/dev` exactly like a real remote-tracking ref).
    """
    worktree = tmp_path / "feature"
    worktree.mkdir()
    _run_git(["init", "-q", "-b", FEATURE_BRANCH], cwd=worktree)
    _run_git(["config", "user.email", "t@example.com"], cwd=worktree)
    _run_git(["config", "user.name", "Test"], cwd=worktree)
    _run_git(["config", "commit.gpgsign", "false"], cwd=worktree)

    (worktree / "sdd" / "specs").mkdir(parents=True)
    (worktree / "sdd" / "specs" / f"{FEATURE_SLUG}.spec.md").write_text("# Spec\n\nDemo spec body.\n", encoding="utf-8")

    for rel_path in _CONVENTION_FILES:
        path = worktree / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Conventions for {rel_path}\n", encoding="utf-8")

    active_dir = worktree / "sdd" / "tasks" / "active"
    completed_dir = worktree / "sdd" / "tasks" / "completed"
    active_dir.mkdir(parents=True)
    completed_dir.mkdir(parents=True)
    (completed_dir / "TASK-1-base.md").write_text(
        "# TASK-1: Base\n\n## Acceptance Criteria\n\n- [x] Base criterion satisfied.\n", encoding="utf-8"
    )
    (active_dir / "TASK-2-thing.md").write_text(
        "# TASK-2: Thing\n\n## Acceptance Criteria\n\n- [ ] Thing criterion pending.\n", encoding="utf-8"
    )

    index_dir = worktree / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True)
    index = {
        "feature": FEATURE_SLUG,
        "feature_id": FEATURE_ID,
        "spec": f"sdd/specs/{FEATURE_SLUG}.spec.md",
        "type": "feature",
        "base_branch": BASE_BRANCH,
        "tasks": [
            {
                "id": "TASK-1",
                "title": "Base",
                "status": "done",
                "depends_on": [],
                "file": "sdd/tasks/completed/TASK-1-base.md",
            },
            {
                "id": "TASK-2",
                "title": "Thing",
                "status": "pending",
                "depends_on": ["TASK-1"],
                "file": "sdd/tasks/active/TASK-2-thing.md",
            },
        ],
    }
    (index_dir / f"{FEATURE_SLUG}.json").write_text(json.dumps(index), encoding="utf-8")

    _run_git(["add", "-A"], cwd=worktree)
    _run_git(["commit", "-q", "-m", "seed"], cwd=worktree)
    base_sha = _run_git(["rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    _run_git(["branch", f"origin/{BASE_BRANCH}", base_sha], cwd=worktree)
    return worktree


def _publish_closed_settlement(
    store: ExecutionEvidenceStore, *, worktree: Path, generation: int = 1
) -> ExecutionSnapshot:
    """Stand in for `SddCoderEngine.end_execution`'s own durable publish (TASK-3565)."""
    snapshot = ExecutionSnapshot(
        execution_id=EXECUTION_ID,
        feature_id=FEATURE_ID,
        worktree_path=str(worktree.resolve()),
        roster_fingerprint="fp-1",
        admitted_attempts={},
        native_reservations={},
        outstanding_job_ids=[],
        local_exclusions=[],
        inherited_exclusions=[],
        status="closed",
        generation=generation,
    )
    asyncio.run(store.put_artifact(EXECUTION_ID, snapshot))
    return snapshot


def test_settlement_and_unknown_gate(tmp_path: Path) -> None:
    """Unknown validation or unclosed execution prevents publication."""
    worktree = _build_repo(tmp_path)
    store = ExecutionEvidenceStore(tmp_path / "durable")

    # No settlement was ever published -- a separate CLI process has no
    # in-memory pool to consult, so this is indistinguishable from busy.
    with pytest.raises(CheckpointBusyError):
        asyncio.run(
            prepare_review_checkpoint(feature=FEATURE_SLUG, worktree=worktree, execution_id=EXECUTION_ID, store=store)
        )

    _publish_closed_settlement(store, worktree=worktree)

    # A closed settlement exists, but an admitted validation is still
    # `pending` (never transitioned) -- checkpoint stays busy.
    registry = BackgroundRegistry(store=store, owner_instance_id="owner-A")
    registration = BackgroundRegistration(
        handle="validation-1",
        execution_id=EXECUTION_ID,
        task_id="TASK-2",
        launch_id="launch-1",
        owner_instance_id="owner-A",
        kind="validation",
        authority="supervisor",
        worktree=str(worktree.resolve()),
        backend="pytest",
    )
    handle = asyncio.run(registry.register(registration))
    with pytest.raises(CheckpointBusyError):
        asyncio.run(
            prepare_review_checkpoint(feature=FEATURE_SLUG, worktree=worktree, execution_id=EXECUTION_ID, store=store)
        )

    # Settling the validation (a durable terminal receipt) lifts the gate.
    log_dir = store.root / "executions" / EXECUTION_ID / "background_logs"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "validation.log"
    log_path.write_text("all green\n", encoding="utf-8")
    asyncio.run(
        registry._record_transition(
            EXECUTION_ID, handle, state="finished", outcome="completed", exit_code=0, log_path=log_path
        )
    )

    checkpoint = asyncio.run(
        prepare_review_checkpoint(feature=FEATURE_SLUG, worktree=worktree, execution_id=EXECUTION_ID, store=store)
    )
    assert checkpoint.execution_id == EXECUTION_ID
    assert len(checkpoint.validation_refs) == 1


def test_stale_head_spec_index_and_conventions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each covered revision change invalidates the handoff before review."""
    worktree = _build_repo(tmp_path)
    store = ExecutionEvidenceStore(tmp_path / "durable")
    # `validate_review_checkpoint` takes no store/root of its own -- it reads
    # the SAME env-var override `scripts.sdd.finalize_task`/`review_checkpoint`
    # use, so it resolves the durable root this test actually published to.
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(store.root))
    _publish_closed_settlement(store, worktree=worktree)

    checkpoint = asyncio.run(
        prepare_review_checkpoint(feature=FEATURE_SLUG, worktree=worktree, execution_id=EXECUTION_ID, store=store)
    )
    # A fresh baseline validates cleanly.
    asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))

    spec_path = worktree / "sdd" / "specs" / f"{FEATURE_SLUG}.spec.md"
    original_spec = spec_path.read_text(encoding="utf-8")
    spec_path.write_text(original_spec + "\nmutated\n", encoding="utf-8")
    with pytest.raises(CheckpointStaleError):
        asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))
    spec_path.write_text(original_spec, encoding="utf-8")
    asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))

    convention_path = worktree / _CONVENTION_FILES[0]
    original_convention = convention_path.read_text(encoding="utf-8")
    convention_path.write_text(original_convention + "\nmutated\n", encoding="utf-8")
    with pytest.raises(CheckpointStaleError):
        asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))
    convention_path.write_text(original_convention, encoding="utf-8")
    asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))

    index_path = worktree / "sdd" / "tasks" / "index" / f"{FEATURE_SLUG}.json"
    original_index = index_path.read_text(encoding="utf-8")
    mutated_index = json.loads(original_index)
    mutated_index["tasks"][1]["status"] = "done"
    index_path.write_text(json.dumps(mutated_index), encoding="utf-8")
    with pytest.raises(CheckpointStaleError):
        asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))
    index_path.write_text(original_index, encoding="utf-8")
    asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))

    # A new commit moves HEAD away from the checkpoint's implementation_head.
    (worktree / "sdd" / "specs" / "extra.md").write_text("extra\n", encoding="utf-8")
    _run_git(["add", "-A"], cwd=worktree)
    _run_git(["commit", "-q", "-m", "moved on"], cwd=worktree)
    with pytest.raises(CheckpointStaleError):
        asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))


def test_durable_neutral_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A new reader with no development conversation recovers criteria, diff and constraints."""
    worktree = _build_repo(tmp_path)
    store = ExecutionEvidenceStore(tmp_path / "durable")
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(store.root))
    _publish_closed_settlement(store, worktree=worktree)

    checkpoint = asyncio.run(
        prepare_review_checkpoint(feature=FEATURE_SLUG, worktree=worktree, execution_id=EXECUTION_ID, store=store)
    )

    # A completely fresh reader loads ONLY the durable, content-addressed
    # evidence -- no conversation, no in-memory engine state.
    fresh_store = ExecutionEvidenceStore(store.root)
    criteria_page = asyncio.run(fresh_store.read_artifact(EXECUTION_ID, checkpoint.criteria_refs[0].artifact_id))
    assert "criterion" in criteria_page["content"]

    task_page = asyncio.run(fresh_store.read_artifact(EXECUTION_ID, checkpoint.task_refs[0].artifact_id))
    assert "Acceptance Criteria" in task_page["content"]

    # Pending work (TASK-2, still 'pending' in the index) survives into both
    # the structured field and the bounded neutral brief -- never silently
    # dropped, never editorialized.
    assert any("TASK-2" in item for item in checkpoint.pending_actions)
    assert "TASK-2" in checkpoint.neutral_brief
    assert len(checkpoint.neutral_brief.encode("utf-8")) <= 8192

    # The immutable diff is recoverable from durable refs alone.
    assert checkpoint.base_sha
    assert checkpoint.implementation_head
    assert checkpoint.branch == FEATURE_BRANCH

    # Re-validating the SAME checkpoint from a brand-new process-local object
    # (nothing carried over except the durable files) still succeeds.
    asyncio.run(validate_review_checkpoint(checkpoint, worktree=worktree))
