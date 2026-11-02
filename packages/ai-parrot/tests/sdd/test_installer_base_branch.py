"""C31 — ``parrot sdd install`` prepares the SDD base branch (TASK-5109), on real temp git repos."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from parrot.sdd.installer import install_sdd_integration, uninstall_sdd_integration


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path) -> None:
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")


def _has(repo: Path, ref: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "show-ref", "--verify", "-q", ref]).returncode == 0


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Fresh repo on ``main`` with one commit and no ``dev``, no remote."""
    r = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    _commit(r)
    return r


@pytest.fixture
def bare(tmp_path: Path) -> Path:
    b = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(b)], check=True)
    return b


def test_creates_local_base_branch_from_head(repo: Path) -> None:
    out = install_sdd_integration(repo)
    assert _git(repo, "rev-parse", "dev") == _git(repo, "rev-parse", "main")
    assert _git(repo, "symbolic-ref", "--short", "HEAD") == "main"
    assert any(a.startswith("dev — created from main") for a in out)
    assert any(a.startswith("note:") and "git remote add origin" in a for a in out)


def test_tracks_origin_base_when_present(repo: Path, bare: Path) -> None:
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", "main:dev")
    _git(repo, "fetch", "-q", "origin")
    out = install_sdd_integration(repo)
    assert any("created, tracking origin/dev" in a for a in out)
    assert _git(repo, "rev-parse", "--abbrev-ref", "dev@{upstream}") == "origin/dev"


def test_unborn_head_warns_and_creates_nothing(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    out = install_sdd_integration(tmp_path)
    assert any(a.startswith("warning:") and "no commit yet" in a for a in out)
    assert not _has(tmp_path, "refs/heads/dev")


def test_not_a_git_repo_warns(tmp_path: Path) -> None:
    out = install_sdd_integration(tmp_path)
    assert any(a.startswith("warning:") and "not a git work tree" in a for a in out)


def test_existing_branch_is_never_moved(repo: Path) -> None:
    _git(repo, "branch", "dev")
    _commit(repo)
    before = _git(repo, "rev-parse", "dev")
    out = install_sdd_integration(repo)
    assert _git(repo, "rev-parse", "dev") == before
    assert any("base branch present" in a for a in out)


def test_missing_origin_is_a_note(repo: Path) -> None:
    out = install_sdd_integration(repo)
    assert any(a.startswith("note:") and "git push -u origin dev" in a for a in out)


def test_origin_without_base_warns(repo: Path, bare: Path) -> None:
    _git(repo, "remote", "add", "origin", str(bare))
    out = install_sdd_integration(repo)
    assert any(a.startswith("warning:") and "git push -u origin dev" in a for a in out)


def test_push_base_pushes_to_bare_remote(repo: Path, bare: Path) -> None:
    _git(repo, "remote", "add", "origin", str(bare))
    install_sdd_integration(repo, push_base=True)
    assert _has(bare, "refs/heads/dev")
    assert _git(repo, "rev-parse", "--abbrev-ref", "dev@{upstream}") == "origin/dev"


def test_push_base_failure_is_a_warning(repo: Path, tmp_path: Path) -> None:
    _git(repo, "remote", "add", "origin", str(tmp_path / "nope.git"))
    out = install_sdd_integration(repo, push_base=True)
    assert any(a.startswith("warning:") and "push to origin failed" in a for a in out)


def test_base_branch_flag_seeds_config(repo: Path) -> None:
    install_sdd_integration(repo, base_branch="main")
    assert json.loads((repo / "sdd/config.json").read_text())["base_branch"] == "main"
    assert not _has(repo, "refs/heads/dev")


def test_base_branch_flag_invalid_name_refuses(repo: Path) -> None:
    with pytest.raises(ValueError):
        install_sdd_integration(repo, base_branch="bad..name")
    assert not (repo / "sdd").exists()


def test_base_branch_flag_conflicting_config_refuses_before_writing(repo: Path) -> None:
    (repo / "sdd").mkdir()
    (repo / "sdd/config.json").write_text(json.dumps({"base_branch": "dev"}))
    before = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if ".git/" not in p.as_posix())
    with pytest.raises(ValueError, match="already sets base_branch"):
        install_sdd_integration(repo, base_branch="main")
    after = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if ".git/" not in p.as_posix())
    assert before == after


def test_dry_run_creates_no_ref(repo: Path) -> None:
    out = install_sdd_integration(repo, dry_run=True)
    assert any(a.startswith("plan: base-branch dev (create from HEAD)") for a in out)
    assert not _has(repo, "refs/heads/dev")


def test_second_run_is_idempotent(repo: Path) -> None:
    install_sdd_integration(repo)
    sha = _git(repo, "rev-parse", "dev")
    out = install_sdd_integration(repo)
    assert _git(repo, "rev-parse", "dev") == sha
    assert any("base branch present" in a for a in out)


def test_uninstall_keeps_base_branch(repo: Path) -> None:
    install_sdd_integration(repo)
    out = uninstall_sdd_integration(repo)
    assert _has(repo, "refs/heads/dev")
    assert isinstance(out, list)
