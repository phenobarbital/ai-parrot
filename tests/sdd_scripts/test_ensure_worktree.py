"""Tests for ``scripts.sdd.ensure_worktree`` — FEAT-552 / TASK-3154."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.sdd.ensure_worktree import EnsureWorktreeError, ensure, main
from scripts.sdd.sdd_meta import FlowMeta, plan_worktree

SLUG = "demo-feature"
FEATURE_ID = "FEAT-999"


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """A clone with an `origin` remote, a `dev` branch, and the SDD artifacts.

    Shape: `origin.git` (bare) <- `work` (the clone under test). `work` has
    sdd/specs/demo-feature.spec.md and sdd/tasks/index/demo-feature.json
    committed on `dev` and pushed, so `origin/dev` carries them.
    """
    origin_dir = tmp_path / "origin.git"
    work_dir = tmp_path / "work"

    # Init bare origin
    subprocess.run(["git", "init", "--bare", str(origin_dir)], check=True)

    # Init work clone
    subprocess.run(["git", "init", str(work_dir)], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=work_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=work_dir, check=True)

    # Create SDD files
    spec_path = work_dir / "sdd/specs/demo-feature.spec.md"
    index_path = work_dir / "sdd/tasks/index/demo-feature.json"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)

    spec_path.write_text("# Demo Feature Spec", encoding="utf-8")
    index_path.write_text('{"status": "pending"}', encoding="utf-8")

    # Commit and push to origin
    subprocess.run(["git", "add", "."], cwd=work_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=work_dir, check=True)
    subprocess.run(["git", "branch", "-M", "dev"], cwd=work_dir, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin_dir)], cwd=work_dir, check=True)
    subprocess.run(["git", "push", "-u", "origin", "dev"], cwd=work_dir, check=True)

    return work_dir


def _plan(branch: str = "dev"):
    return plan_worktree(FlowMeta(type="feature", base_branch=branch), slug=SLUG, feature_id=FEATURE_ID)


def test_ensure_creates_worktree_when_absent(tmp_git_repo: Path) -> None:
    """First call creates the branch and the directory and reports created=True."""
    path, created = ensure(_plan(), repo_root=tmp_git_repo)
    assert created is True
    assert path.is_dir()
    assert path.name == f"feat-{FEATURE_ID}-{SLUG}"


def test_ensure_is_idempotent(tmp_git_repo: Path) -> None:
    """Second call reuses: same path, created=False, still exactly one branch."""
    first, _ = ensure(_plan(), repo_root=tmp_git_repo)
    second, created = ensure(_plan(), repo_root=tmp_git_repo)
    assert second == first and created is False

    # Assert `git branch --list feat-FEAT-999-demo-feature` yields one line
    res = subprocess.run(
        ["git", "branch", "--list", f"feat-{FEATURE_ID}-{SLUG}"],
        cwd=tmp_git_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    assert len(lines) == 1


def test_ensure_rejects_path_with_foreign_branch(tmp_git_repo: Path) -> None:
    """A worktree at the target path on another branch is an error, not a reuse."""
    # Create the worktree first
    plan = _plan()
    path, created = ensure(plan, repo_root=tmp_git_repo)
    assert created is True

    # Force its branch elsewhere or create a different branch and check it out there.
    # Let's create a new branch 'other-branch' and check it out in that worktree.
    subprocess.run(["git", "checkout", "-b", "other-branch"], cwd=path, check=True)

    with pytest.raises(EnsureWorktreeError) as exc_info:
        ensure(plan, repo_root=tmp_git_repo)
    assert "expected branch" in str(exc_info.value)


def test_ensure_rejects_existing_unchecked_branch(tmp_git_repo: Path) -> None:
    """A leftover branch with no worktree must be reported, not reused blindly."""
    plan = _plan()
    # Create a branch with the target name but no worktree
    subprocess.run(["git", "branch", plan.name], cwd=tmp_git_repo, check=True)

    with pytest.raises(EnsureWorktreeError) as exc_info:
        ensure(plan, repo_root=tmp_git_repo)
    assert plan.name in str(exc_info.value)
    assert "already exists but is not checked out" in str(exc_info.value)


def test_ensure_requires_paths_visible(tmp_git_repo: Path) -> None:
    """Branching from a base that lacks the task artifacts must fail loudly."""
    plan = _plan()
    with pytest.raises(EnsureWorktreeError) as exc_info:
        ensure(plan, repo_root=tmp_git_repo, require_paths=["sdd/tasks/index/absent.json"])
    assert "Verification failed" in str(exc_info.value)

    # Assert that the half-created worktree is not left behind
    target_path = (tmp_git_repo / plan.path).resolve()
    assert not target_path.exists()


def test_ensure_dry_run_mutates_nothing(tmp_git_repo: Path) -> None:
    """--dry-run resolves and reports; `git worktree list` is unchanged."""
    res_before = subprocess.run(
        ["git", "worktree", "list"], cwd=tmp_git_repo, capture_output=True, text=True, check=True
    )
    before_list = res_before.stdout

    path, created = ensure(_plan(), repo_root=tmp_git_repo, dry_run=True)
    assert created is True

    res_after = subprocess.run(
        ["git", "worktree", "list"], cwd=tmp_git_repo, capture_output=True, text=True, check=True
    )
    after_list = res_after.stdout

    assert before_list == after_list


def test_ensure_json_output_shape(tmp_git_repo: Path, capsys, monkeypatch) -> None:
    """--json emits one object with name/path/base_ref/created."""
    monkeypatch.chdir(tmp_git_repo)

    # First run (creates)
    ret = main(["--slug", SLUG, "--feature-id", FEATURE_ID, "--json"])
    assert ret == 0
    out, err = capsys.readouterr()
    data = json.loads(out.strip())
    assert data["name"] == f"feat-{FEATURE_ID}-{SLUG}"
    assert data["created"] is True
    assert "base_ref" in data
    assert "path" in data

    # Second run (reuses)
    ret = main(["--slug", SLUG, "--feature-id", FEATURE_ID, "--json"])
    assert ret == 0
    out, err = capsys.readouterr()
    data = json.loads(out.strip())
    assert data["created"] is False


def test_json_output_includes_worktree_path_alias(tmp_git_repo: Path, capsys, monkeypatch) -> None:
    """sdd-planner/sdd-research read ``worktree_path`` from the JSON object
    for their PlannerOutput/ResearchOutput contracts (spec §8) — the CLI
    must actually emit that key, not just ``path`` (code review fixup)."""
    monkeypatch.chdir(tmp_git_repo)

    ret = main(["--slug", SLUG, "--feature-id", FEATURE_ID, "--json"])
    assert ret == 0
    out, _err = capsys.readouterr()
    data = json.loads(out.strip())
    assert "worktree_path" in data
    assert data["worktree_path"] == data["path"]


def test_main_infers_hotfix_from_jira_key_alone(tmp_git_repo: Path, capsys, monkeypatch) -> None:
    """The documented invocation ``--slug <slug> --jira-key <KEY>`` (CLAUDE.md,
    sdd-research.md) must work without also requiring ``--type``/
    ``--base-branch`` — ``resolve_flow()`` has no other signal here that this
    is a hotfix run, so ``main()`` must infer it (code review fixup)."""
    # Hotfix worktrees branch from origin/main; give the fixture's origin a
    # main branch mirroring dev so the fetch/worktree-add in ensure() succeeds.
    subprocess.run(["git", "push", "origin", "dev:main"], cwd=tmp_git_repo, check=True)
    monkeypatch.chdir(tmp_git_repo)

    ret = main(["--slug", SLUG, "--jira-key", "NAV-8036", "--json"])
    assert ret == 0
    out, _err = capsys.readouterr()
    data = json.loads(out.strip())
    assert data["name"] == f"hotfix-NAV-8036-{SLUG}"
    assert data["base_ref"] == "origin/main"


def test_ensure_rejects_absolute_require_paths(tmp_git_repo: Path) -> None:
    """An absolute ``require_paths`` entry must be rejected outright, not
    silently pass verification — ``Path(x) / <absolute>`` discards ``x``,
    which would make Step 5 check a path outside the worktree entirely and
    report success regardless (code review fixup)."""
    plan = _plan()
    with pytest.raises(EnsureWorktreeError) as exc_info:
        ensure(plan, repo_root=tmp_git_repo, require_paths=["/etc/hostname"])
    assert "repo-relative" in str(exc_info.value)
