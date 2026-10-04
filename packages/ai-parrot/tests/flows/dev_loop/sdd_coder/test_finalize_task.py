"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers.

Every scenario builds a real temporary git repository (never a mock of git
itself) and drives `scripts.sdd.finalize_task` against the real
`scripts/sdd/close_task.sh` primitive, matching the task's Codebase
Contract: "Usar repo temporal real con close_task.sh, snapshots de
index/staging antes/después; tamper hash refs, notes deterministas y
payload distinto requiere operación nueva."
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import scripts.sdd as scripts_sdd_pkg
from parrot.flows.dev_loop.sdd_coder.optimization_models import EvidenceRef, TaskCompletionEvidence
from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root
from scripts.sdd.finalize_task import (
    InvalidEvidenceError,
    TaskEvidenceStaleError,
    TaskTwinConflictError,
    _hash_evidence,
    _journal_paths,
    _write_journal,
    finalize_task,
)

_REAL_CLOSE_TASK_SH = Path(scripts_sdd_pkg.__file__).parent / "close_task.sh"

_TASK_MD_TEMPLATE = """# {task_id}: Demo task

**Feature**: {feature_slug}
**Spec**: sdd/specs/{feature_slug}.spec.md
**Status**: pending
**Priority**: high
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Demo task fixture for finalize_task regression tests.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `{impl_file}` | CREATE | Demo implementation file |

## Acceptance Criteria

- [ ] Demo criterion.

## Completion Note

Pendiente de ejecución.
"""


def _git(args: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def _porcelain_status(repo_root: Path) -> dict[str, str]:
    """Map `path -> XY` from `git status --porcelain --no-renames`.

    `--no-renames` keeps a task's active->completed move as separate D/A
    lines instead of a heuristic `R ` pair, so assertions are exact.
    """
    out = _git(["status", "--porcelain", "--no-renames"], cwd=repo_root).stdout
    status: dict[str, str] = {}
    for line in out.splitlines():
        if not line:
            continue
        status[line[3:]] = line[:2]
    return status


def _init_git_repo(repo_root: Path) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], cwd=repo_root)
    _git(["config", "user.email", "sdd-tests@example.com"], cwd=repo_root)
    _git(["config", "user.name", "SDD Tests"], cwd=repo_root)
    _git(["config", "commit.gpgsign", "false"], cwd=repo_root)


def _build_repo(
    repo_root: Path,
    *,
    task_id: str,
    feature_slug: str,
    impl_file: str = "src/demo/foo.py",
    extra_tracked_files: dict[str, bytes] | None = None,
) -> tuple[Path, Path, str]:
    """Build a real temp git repo with a task file, per-spec index and one implementation commit.

    `extra_tracked_files`, when given, is committed BEFORE the implementation
    commit -- so the returned `implementation_sha` (the LAST commit, HEAD)
    still points only at `impl_file`, while those extra paths are already
    tracked history a test can dirty/stage afterward without moving HEAD.

    Returns `(task_md_path, index_path, implementation_sha)`.
    """
    _init_git_repo(repo_root)

    dest_close_task = repo_root / "scripts" / "sdd" / "close_task.sh"
    dest_close_task.parent.mkdir(parents=True, exist_ok=True)
    dest_close_task.write_bytes(_REAL_CLOSE_TASK_SH.read_bytes())
    dest_close_task.chmod(0o755)

    active_dir = repo_root / "sdd" / "tasks" / "active"
    active_dir.mkdir(parents=True, exist_ok=True)
    task_md_path = active_dir / f"{task_id}-demo-task.md"
    task_md_path.write_text(
        _TASK_MD_TEMPLATE.format(task_id=task_id, feature_slug=feature_slug, impl_file=impl_file),
        encoding="utf-8",
    )

    index_dir = repo_root / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    index_path = index_dir / f"{feature_slug}.json"
    index_path.write_text(
        json.dumps(
            {
                "feature": feature_slug,
                "feature_id": "FEAT-9001",
                "spec": f"sdd/specs/{feature_slug}.spec.md",
                "type": "feature",
                "base_branch": "dev",
                "created_at": "2026-01-01T00:00:00+00:00",
                "completed_at": None,
                "tasks": [
                    {
                        "id": task_id,
                        "feature_id": "FEAT-9001",
                        "feature": feature_slug,
                        "status": "pending",
                        "depends_on": [],
                        "file": f"sdd/tasks/active/{task_md_path.name}",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    _git(["add", "-A"], cwd=repo_root)
    _git(["commit", "-q", "-m", "base"], cwd=repo_root)

    if extra_tracked_files:
        for rel_path, content in extra_tracked_files.items():
            extra_path = repo_root / rel_path
            extra_path.parent.mkdir(parents=True, exist_ok=True)
            extra_path.write_bytes(content)
        _git(["add", "-A"], cwd=repo_root)
        _git(["commit", "-q", "-m", "extra tracked files"], cwd=repo_root)

    impl_path = repo_root / impl_file
    impl_path.parent.mkdir(parents=True, exist_ok=True)
    impl_path.write_text("value = 1\n", encoding="utf-8")
    _git(["add", "--", impl_file], cwd=repo_root)
    _git(["commit", "-q", "-m", f"feat: {task_id} implementation"], cwd=repo_root)
    implementation_sha = _git(["rev-parse", "HEAD"], cwd=repo_root).stdout.strip()

    return task_md_path, index_path, implementation_sha


def _make_evidence_ref(durable_root: Path, relative_path: str, content: bytes) -> EvidenceRef:
    path = durable_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    return EvidenceRef(
        artifact_id=digest,
        sha256=digest,
        relative_path=relative_path,
        size_bytes=len(content),
        media_type="application/json",
    )


def _build_evidence(
    durable_root: Path,
    *,
    task_id: str,
    feature_slug: str,
    implementation_sha: str,
    completion_facts: dict[str, object] | None = None,
) -> TaskCompletionEvidence:
    exec_id = "11111111-1111-4111-8111-111111111111"
    review_ref = _make_evidence_ref(
        durable_root, f"executions/{exec_id}/artifacts/review-{task_id}.json", b'{"verdict": "approved"}'
    )
    validation_ref = _make_evidence_ref(
        durable_root, f"executions/{exec_id}/artifacts/validation-{task_id}.json", b'{"tests": "passed"}'
    )
    return TaskCompletionEvidence(
        feature_slug=feature_slug,
        task_id=task_id,
        implementation_sha=implementation_sha,
        validation_refs=[validation_ref],
        review_evidence=review_ref,
        fix_commits=[],
        completion_facts=completion_facts or {"tests_passed": True},
    )


def test_semantic_evidence_and_head_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing review, red tests or stale implementation SHA prevent mutation."""
    task_id = "TASK-9101"
    feature_slug = "finalize-demo-a"
    task_md_path, index_path, implementation_sha = _build_repo(
        tmp_path / "repo", task_id=task_id, feature_slug=feature_slug
    )
    repo_root = task_md_path.parents[3]
    durable_root = tmp_path / "durable"
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(durable_root))

    original_md = task_md_path.read_text(encoding="utf-8")
    original_index = index_path.read_text(encoding="utf-8")

    # (a) No validation evidence at all ("red tests") -> invalid input, nothing mutated.
    review_ref = _make_evidence_ref(durable_root, "executions/e/artifacts/review.json", b'{"verdict": "approved"}')
    bare_evidence = TaskCompletionEvidence(
        feature_slug=feature_slug,
        task_id=task_id,
        implementation_sha=implementation_sha,
        validation_refs=[],
        review_evidence=review_ref,
        fix_commits=[],
        completion_facts={},
    )
    with pytest.raises(InvalidEvidenceError):
        finalize_task(evidence=bare_evidence, worktree=repo_root, expected_head=implementation_sha)
    assert task_md_path.read_text(encoding="utf-8") == original_md
    assert index_path.read_text(encoding="utf-8") == original_index
    assert not (repo_root / "sdd" / "tasks" / "completed").exists()

    # (b) expected_head disagrees with evidence.implementation_sha -> stale, nothing mutated.
    evidence = _build_evidence(
        durable_root, task_id=task_id, feature_slug=feature_slug, implementation_sha=implementation_sha
    )
    with pytest.raises(TaskEvidenceStaleError):
        finalize_task(evidence=evidence, worktree=repo_root, expected_head="0" * 40)
    assert task_md_path.read_text(encoding="utf-8") == original_md
    assert index_path.read_text(encoding="utf-8") == original_index

    # (c) expected_head matches the evidence, but the worktree HEAD has since moved -> stale.
    _git(["commit", "--allow-empty", "-q", "-m", "drift"], cwd=repo_root)
    with pytest.raises(TaskEvidenceStaleError):
        finalize_task(evidence=evidence, worktree=repo_root, expected_head=implementation_sha)
    assert task_md_path.read_text(encoding="utf-8") == original_md
    assert index_path.read_text(encoding="utf-8") == original_index


def test_crash_resume_and_twin_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each journal phase resumes once and divergent twins remain intact."""
    task_id = "TASK-9102"
    feature_slug = "finalize-demo-b"
    task_md_path, index_path, implementation_sha = _build_repo(
        tmp_path / "repo", task_id=task_id, feature_slug=feature_slug
    )
    repo_root = task_md_path.parents[3]
    durable_root = tmp_path / "durable"
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(durable_root))
    evidence = _build_evidence(
        durable_root, task_id=task_id, feature_slug=feature_slug, implementation_sha=implementation_sha
    )

    # -- a divergent twin (active + completed disagree) is never destroyed. --
    completed_dir = repo_root / "sdd" / "tasks" / "completed"
    completed_dir.mkdir(parents=True, exist_ok=True)
    twin_path = completed_dir / task_md_path.name
    twin_path.write_text("# totally different content, not produced by this wrapper\n", encoding="utf-8")
    original_active = task_md_path.read_text(encoding="utf-8")

    with pytest.raises(TaskTwinConflictError):
        finalize_task(evidence=evidence, worktree=repo_root, expected_head=implementation_sha)
    assert task_md_path.exists()
    assert task_md_path.read_text(encoding="utf-8") == original_active
    assert twin_path.read_text(encoding="utf-8") == "# totally different content, not produced by this wrapper\n"

    twin_path.unlink()  # clear the poisoned twin before the real run

    # -- first run closes the task. --
    result = finalize_task(evidence=evidence, worktree=repo_root, expected_head=implementation_sha)
    assert result["replayed"] is False
    assert not task_md_path.exists()
    completed_path = completed_dir / task_md_path.name
    assert completed_path.is_file()
    closed_note = result["note"]
    assert closed_note.strip() in completed_path.read_text(encoding="utf-8")

    # -- idempotent replay: identical evidence returns the same result, no re-mutation. --
    staged_before = _git(["diff", "--cached", "--name-only"], cwd=repo_root).stdout
    replay = finalize_task(evidence=evidence, worktree=repo_root, expected_head=implementation_sha)
    assert replay["replayed"] is True
    assert replay["note"] == closed_note
    staged_after = _git(["diff", "--cached", "--name-only"], cwd=repo_root).stdout
    assert staged_before == staged_after

    # -- a different (tampered) evidence payload for an already-closed task is rejected. --
    before_tamper = completed_path.read_text(encoding="utf-8")
    tampered = _build_evidence(
        durable_root,
        task_id=task_id,
        feature_slug=feature_slug,
        implementation_sha=implementation_sha,
        completion_facts={"tests_passed": True, "tampered": True},
    )
    with pytest.raises(TaskEvidenceStaleError):
        finalize_task(evidence=tampered, worktree=repo_root, expected_head=implementation_sha)
    assert completed_path.read_text(encoding="utf-8") == before_tamper

    # -- crash resume: a journal at phase "validated" (crash before any mutation)
    #    resumes to completion once, reusing the journaled closed_at instead of
    #    restarting the operation. --
    task_id_c = "TASK-9103"
    task_md_path_c, index_path_c, implementation_sha_c = _build_repo(
        tmp_path / "repo_c", task_id=task_id_c, feature_slug=feature_slug
    )
    repo_root_c = task_md_path_c.parents[3]
    evidence_c = _build_evidence(
        durable_root, task_id=task_id_c, feature_slug=feature_slug, implementation_sha=implementation_sha_c
    )

    durable_root_resolved = resolve_durable_root(str(durable_root), worktree_base_path=str(repo_root_c))
    journal_path, _lock_path = _journal_paths(durable_root_resolved, feature_slug, task_id_c)
    evidence_hash = _hash_evidence(evidence_c)
    operation_key = f"{task_id_c}:{implementation_sha_c}:{evidence_hash}"
    frozen_closed_at = "2020-01-01T00:00:00+00:00"
    _write_journal(
        journal_path,
        operation_key=operation_key,
        phase="validated",
        note="placeholder-note-from-before-the-crash",
        closed_at=frozen_closed_at,
        feature_slug=feature_slug,
        task_id=task_id_c,
    )

    result_c = finalize_task(evidence=evidence_c, worktree=repo_root_c, expected_head=implementation_sha_c)
    assert result_c["replayed"] is False
    assert f"Closed at (UTC): {frozen_closed_at}" in result_c["note"]
    completed_path_c = repo_root_c / "sdd" / "tasks" / "completed" / task_md_path_c.name
    assert completed_path_c.is_file()
    assert not task_md_path_c.exists()


def test_preserve_foreign_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the task and its index are staged; unrelated staged/unstaged content stays unchanged."""
    task_id = "TASK-9104"
    other_task_id = "TASK-9199"
    feature_slug = "finalize-demo-c"
    other_active_relpath = f"sdd/tasks/active/{other_task_id}-other-task.md"
    task_md_path, index_path, implementation_sha = _build_repo(
        tmp_path / "repo",
        task_id=task_id,
        feature_slug=feature_slug,
        extra_tracked_files={other_active_relpath: b"# other pending task\n\noriginal\n"},
    )
    repo_root = task_md_path.parents[3]
    durable_root = tmp_path / "durable"
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(durable_root))
    evidence = _build_evidence(
        durable_root, task_id=task_id, feature_slug=feature_slug, implementation_sha=implementation_sha
    )

    # Foreign, UNSTAGED pending edit to a different task's active file (tracked
    # since the "base" commit, dirtied here WITHOUT creating a new commit so
    # `implementation_sha`/HEAD is untouched).
    other_active = repo_root / other_active_relpath
    other_active.write_text("# other pending task\n\nEDITED, not yet staged\n", encoding="utf-8")

    # Foreign, STAGED but uncommitted change to an unrelated source file.
    foreign_src = repo_root / "src" / "unrelated.py"
    foreign_src.parent.mkdir(parents=True, exist_ok=True)
    foreign_src.write_text("x = 1\n", encoding="utf-8")
    _git(["add", "--", "src/unrelated.py"], cwd=repo_root)

    before = _porcelain_status(repo_root)
    assert before[other_active_relpath] == " M"
    assert before["src/unrelated.py"] == "A "
    other_active_before = other_active.read_text(encoding="utf-8")

    result = finalize_task(evidence=evidence, worktree=repo_root, expected_head=implementation_sha)

    # Our own task closed normally.
    assert not task_md_path.exists()
    completed_relpath = f"sdd/tasks/completed/{task_md_path.name}"
    assert (repo_root / completed_relpath).is_file()
    index_relpath = f"sdd/tasks/index/{feature_slug}.json"
    assert set(result["staged_paths"]) <= {completed_relpath, index_relpath}
    assert result["removed_paths"] == [f"sdd/tasks/active/{task_md_path.name}"]

    after = _porcelain_status(repo_root)

    # The foreign unstaged edit is completely untouched: same content, still unstaged.
    assert other_active.read_text(encoding="utf-8") == other_active_before
    assert after[other_active_relpath] == " M"

    # The foreign pre-staged file remains staged, byte-identical, never re-touched.
    assert after["src/unrelated.py"] == "A "

    # Only our own task's paths changed status.
    assert after.get(f"sdd/tasks/active/{task_md_path.name}") == "D "
    assert after.get(completed_relpath) == "A "
    assert after.get(index_relpath) == "M "
