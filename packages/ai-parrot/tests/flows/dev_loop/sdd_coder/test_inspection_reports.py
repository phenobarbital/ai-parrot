"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from parrot.flows.dev_loop.sdd_coder import inspection
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore

EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
FOREIGN_EXECUTION_ID = "22222222-2222-4222-8222-222222222222"
FEATURE_BRANCH = "feat-branch"
FEATURE_SLUG = "myfeature"


def _run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_feature_worktree(tmp_path: Path) -> Path:
    """A real, tiny git repo standing in for a feature worktree: an index + a task file."""
    worktree = tmp_path / "feature"
    worktree.mkdir()
    _run_git(["init", "-q", "-b", FEATURE_BRANCH], cwd=worktree)
    _run_git(["config", "user.email", "t@example.com"], cwd=worktree)
    _run_git(["config", "user.name", "Test"], cwd=worktree)

    index_dir = worktree / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True)
    index = {
        "feature": FEATURE_SLUG,
        "feature_id": "FEAT-999",
        "tasks": [
            {"id": "TASK-1", "title": "Base", "status": "done", "depends_on": [], "file": ""},
            {
                "id": "TASK-2",
                "title": "Needs TASK-1 and TASK-9",
                "status": "pending",
                "depends_on": ["TASK-1", "TASK-9"],
                "file": "sdd/tasks/active/TASK-2-thing.md",
            },
        ],
    }
    (index_dir / f"{FEATURE_SLUG}.json").write_text(json.dumps(index), encoding="utf-8")

    tasks_dir = worktree / "sdd" / "tasks" / "active"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "TASK-2-thing.md").write_text(
        "# TASK-2\n\n## Files to Create / Modify\n\n- `pkg/a.py`\n", encoding="utf-8"
    )

    _run_git(["add", "-A"], cwd=worktree)
    _run_git(["commit", "-q", "-m", "seed"], cwd=worktree)
    return worktree


def _create_attempt_branch(
    worktree: Path, *, task_id: str, attempt: int, execution_id: str, extra_files: dict[str, str]
) -> str:
    """Create `<FEATURE_BRANCH>--<task_id>-a<attempt>-<exec hex>` with one commit, mirroring `_branch_for`."""
    suffix = f"{task_id}-a{attempt}-{execution_id.replace('-', '')}"
    branch = f"{FEATURE_BRANCH}--{suffix}"
    _run_git(["checkout", "-b", branch], cwd=worktree)
    for rel_path, content in extra_files.items():
        path = worktree / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _run_git(["add", "-A"], cwd=worktree)
    _run_git(["commit", "-q", "-m", f"{task_id} attempt {attempt}"], cwd=worktree)
    _run_git(["checkout", FEATURE_BRANCH], cwd=worktree)
    return branch


def test_context_preserves_blockers(tmp_path: Path) -> None:
    """Dependency status and file contract determine readiness without modifying index."""
    worktree = _init_feature_worktree(tmp_path)
    store = ExecutionEvidenceStore(tmp_path / "evidence")

    result = asyncio.run(
        inspection.task_context(
            feature=FEATURE_SLUG, worktree=worktree, task_id="TASK-2", execution_id=EXECUTION_ID, store=store
        )
    )

    assert result["ready"] is False
    assert result["blockers"] == ["TASK-9"]
    assert result["dependency_status"] == {"TASK-1": "done", "TASK-9": "blocked"}
    assert result["contract"] == ["pkg/a.py"]
    assert result["task_md_ref"]["sha256"]

    # Read-only: the index and task file on disk are untouched.
    index_path = worktree / "sdd" / "tasks" / "index" / f"{FEATURE_SLUG}.json"
    on_disk = json.loads(index_path.read_text(encoding="utf-8"))
    assert on_disk["tasks"][1]["status"] == "pending"

    # A task with every dependency satisfied is `ready`.
    ready_result = asyncio.run(
        inspection.task_context(
            feature=FEATURE_SLUG, worktree=worktree, task_id="TASK-1", execution_id=EXECUTION_ID, store=store
        )
    )
    assert ready_result["blockers"] == []


def test_delivery_scope_and_unknown_evidence(tmp_path: Path) -> None:
    """Report matches existing fidelity and missing checks remain unknown."""
    worktree = _init_feature_worktree(tmp_path)
    store = ExecutionEvidenceStore(tmp_path / "evidence")

    branch = _create_attempt_branch(
        worktree,
        task_id="TASK-2",
        attempt=1,
        execution_id=EXECUTION_ID,
        extra_files={"pkg/a.py": "print('hi')\n", "pkg/unexpected.py": "print('oops')\n"},
    )

    result = asyncio.run(
        inspection.delivery_report(
            feature=FEATURE_SLUG, worktree=worktree, task_id="TASK-2", execution_id=EXECUTION_ID, store=store
        )
    )

    assert result["branch"] == branch
    assert result["attempt"] == 1
    assert result["feature_branch"] == FEATURE_BRANCH
    assert set(result["changed_files"]) == {"pkg/a.py", "pkg/unexpected.py"}
    assert result["unexpected_files"] == ["pkg/unexpected.py"]
    assert result["fidelity_ok"] is False
    assert result["commits"] == 1
    # Never runs a merge, autofix, lint or test: no producer in this task's
    # scope publishes that evidence yet, so it is honestly "unknown".
    assert result["lint_evidence"] == "unknown"
    assert result["test_evidence"] == "unknown"
    assert result["review_evidence"] == "unknown"
    # The feature branch itself was never advanced by this call.
    rc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", branch, FEATURE_BRANCH], cwd=worktree, check=False
    ).returncode
    assert rc != 0


def test_ownership_and_snapshot_race(tmp_path: Path) -> None:
    """Foreign worktree and changed revisions do not yield a trustworthy delivery snapshot."""
    worktree = _init_feature_worktree(tmp_path)
    store = ExecutionEvidenceStore(tmp_path / "evidence")

    _create_attempt_branch(
        worktree,
        task_id="TASK-2",
        attempt=1,
        execution_id=EXECUTION_ID,
        extra_files={"pkg/a.py": "print('hi')\n"},
    )

    # A foreign execution_id's own hex never matches the real attempt branch's
    # embedded suffix, so no branch is ever adopted on its behalf.
    with pytest.raises(LookupError):
        asyncio.run(
            inspection.delivery_report(
                feature=FEATURE_SLUG,
                worktree=worktree,
                task_id="TASK-2",
                execution_id=FOREIGN_EXECUTION_ID,
                store=store,
            )
        )

    # The legitimate owner still gets a report; a sub-worktree that was
    # never materialized (or was already cleaned up) degrades to
    # "unknown", never a fabricated clean status.
    result = asyncio.run(
        inspection.delivery_report(
            feature=FEATURE_SLUG, worktree=worktree, task_id="TASK-2", execution_id=EXECUTION_ID, store=store
        )
    )
    assert result["sub_worktree_present"] is False
    assert result["sub_worktree_dirty"] is None
    assert result["branch_head_sha"]

    # A second, later attempt for the SAME task/execution is reported as the
    # new latest -- the snapshot never sticks to a stale revision.
    _create_attempt_branch(
        worktree,
        task_id="TASK-2",
        attempt=2,
        execution_id=EXECUTION_ID,
        extra_files={"pkg/a.py": "print('hi v2')\n"},
    )
    second_result = asyncio.run(
        inspection.delivery_report(
            feature=FEATURE_SLUG, worktree=worktree, task_id="TASK-2", execution_id=EXECUTION_ID, store=store
        )
    )
    assert second_result["attempt"] == 2
    assert second_result["branch_head_sha"] != result["branch_head_sha"]
