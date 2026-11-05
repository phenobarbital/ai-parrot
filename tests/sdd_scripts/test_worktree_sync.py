"""Real temporary Git integration tests for worktree sync."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from parrot.sdd.scripts import worktree_sync


def _run(path: Path, *args: str) -> str:
    """Run Git in a disposable repository and return stdout."""
    return subprocess.run(["git", "-C", str(path), *args], text=True, capture_output=True, check=True).stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a primary clone, its bare origin, and a linked feature worktree."""
    origin = tmp_path / "origin.git"
    primary = tmp_path / "primary"
    feature = tmp_path / "feature"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "clone", str(origin), str(primary)], check=True, capture_output=True, text=True)
    _run(primary, "config", "user.email", "test@example.invalid")
    _run(primary, "config", "user.name", "Sync Test")
    (primary / "shared.txt").write_text("base\n", encoding="utf-8")
    _run(primary, "add", "shared.txt")
    _run(primary, "commit", "-m", "initial")
    _run(primary, "branch", "-M", "dev")
    _run(primary, "push", "-u", "origin", "dev")
    _run(primary, "worktree", "add", "-b", "feat-FEAT-999-sync", str(feature), "dev")
    return origin, primary, feature


def _configure_sandbox(feature: Path) -> None:
    """Install the host-owned read-only sandbox prerequisite in a disposable worktree."""
    _run(feature, "remote", "set-url", "origin", "git@github.com:example/sync.git")
    _run(feature, "config", "extensions.worktreeConfig", "true")
    _run(feature, "config", "--worktree", "remote.origin.pushurl", "no_push")


def _install_gh_stub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, responses: dict[str, tuple[dict[str, object], str]]
) -> None:
    """Provide deterministic metadata and patch responses through a PATH-local gh stub."""
    fixtures = tmp_path / "gh-fixtures"
    fixtures.mkdir()
    for sha, (metadata, patch) in responses.items():
        (fixtures / f"{sha}.json").write_text(json.dumps(metadata), encoding="utf-8")
        (fixtures / f"{sha}.patch").write_text(patch, encoding="utf-8")
    executable = tmp_path / "gh"
    executable.write_text(
        "#!/bin/sh\n"
        'for argument in "$@"; do case "$argument" in repos/*) endpoint=$argument ;; esac; done\n'
        "sha=${endpoint##*/}\n"
        'case "$*" in\n'
        "  *'Accept: application/vnd.github.patch'*) cat \"$GH_FIXTURES/$sha.patch\" ;;\n"
        '  *) cat "$GH_FIXTURES/$sha.json" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("GH_FIXTURES", str(fixtures))
    monkeypatch.setenv("PATH", f"{tmp_path}:{Path('/usr/bin')}")


def _patch_response(primary: Path, sha: str) -> tuple[dict[str, object], str]:
    """Build the two gh API representations of a real local commit."""
    subject = _run(primary, "show", "-s", "--format=%s", sha)
    parent = _run(primary, "rev-parse", f"{sha}^")
    patch = _run(primary, "format-patch", "--stdout", "-1", sha)
    return {"sha": sha, "parents": [{"sha": parent}], "commit": {"message": subject}}, patch


def test_host_merge_from_outside(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A new base commit is integrated into a registered feature worktree."""
    _origin, primary, feature = _repository(tmp_path)
    (primary / "base.txt").write_text("from base\n", encoding="utf-8")
    _run(primary, "add", "base.txt")
    _run(primary, "commit", "-m", "base update")
    _run(primary, "push")

    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    result = worktree_sync.sync(feature, "dev")

    assert result.exit_code == worktree_sync.EXIT_OK
    assert result.status == "synced"
    assert (feature / "base.txt").read_text(encoding="utf-8") == "from base\n"
    assert _run(feature, "status", "--porcelain") == ""


def test_conflict_aborts_and_restores_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Conflicting merge restores HEAD, index and tree and reports paths."""
    _origin, primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    (feature / "shared.txt").write_text("feature\n", encoding="utf-8")
    _run(feature, "add", "shared.txt")
    _run(feature, "commit", "-m", "feature change")
    before = _run(feature, "rev-parse", "HEAD")
    (primary / "shared.txt").write_text("base change\n", encoding="utf-8")
    _run(primary, "add", "shared.txt")
    _run(primary, "commit", "-m", "base change")
    _run(primary, "push")

    result = worktree_sync.sync(feature, "dev")

    assert result.exit_code == worktree_sync.EXIT_CONFLICT
    assert result.status == "conflict"
    assert result.before == result.after == before
    assert result.conflicts == ["shared.txt"]
    assert _run(feature, "status", "--porcelain") == ""
    assert (feature / "shared.txt").read_text(encoding="utf-8") == "feature\n"


def test_stale_base_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Advisory covers ahead, current, and sandbox cases without changing the tree."""
    _origin, primary, feature = _repository(tmp_path)
    (primary / "base.txt").write_text("from base\n", encoding="utf-8")
    _run(primary, "add", "base.txt")
    _run(primary, "commit", "-m", "base update")
    _run(primary, "push")
    before = _run(feature, "rev-parse", "HEAD")

    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    summary = worktree_sync.stale_base_summary(feature, "dev")
    assert "1 commit(s) ahead" in summary
    assert _run(feature, "rev-parse", "HEAD") == before
    assert _run(feature, "status", "--porcelain") == ""

    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")
    assert worktree_sync.stale_base_summary(feature, "dev").startswith("stale-base check skipped:")


def test_sandbox_cherry_pick_via_gh_patch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Host-configured sandbox applies a gh mailbox patch with its source-SHA trailer."""
    _origin, primary, feature = _repository(tmp_path)
    _configure_sandbox(feature)
    (primary / "patch.txt").write_text("from gh\n", encoding="utf-8")
    _run(primary, "add", "patch.txt")
    _run(primary, "commit", "-m", "gh patch")
    sha = _run(primary, "rev-parse", "HEAD")
    _install_gh_stub(tmp_path, monkeypatch, {sha: _patch_response(primary, sha)})
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")

    result = worktree_sync.sync(feature, "dev", cherry_picks=[sha])

    assert result.status == "synced"
    assert (feature / "patch.txt").read_text(encoding="utf-8") == "from gh\n"
    assert f"(cherry picked from commit {sha})" in _run(feature, "log", "-1", "--format=%B")
    assert _run(feature, "config", "--get-all", "remote.origin.pushurl") == "no_push"


def test_sandbox_second_patch_conflict_restores_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A later git-am conflict aborts the single sandbox batch back to its original tree."""
    _origin, primary, feature = _repository(tmp_path)
    _configure_sandbox(feature)
    (primary / "first.txt").write_text("first\n", encoding="utf-8")
    _run(primary, "add", "first.txt")
    _run(primary, "commit", "-m", "first patch")
    first = _run(primary, "rev-parse", "HEAD")
    (primary / "shared.txt").write_text("base change\n", encoding="utf-8")
    _run(primary, "add", "shared.txt")
    _run(primary, "commit", "-m", "conflicting patch")
    second = _run(primary, "rev-parse", "HEAD")
    (feature / "shared.txt").write_text("feature change\n", encoding="utf-8")
    _run(feature, "add", "shared.txt")
    _run(feature, "commit", "-m", "feature change")
    before = _run(feature, "rev-parse", "HEAD")
    _install_gh_stub(
        tmp_path,
        monkeypatch,
        {first: _patch_response(primary, first), second: _patch_response(primary, second)},
    )
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")

    result = worktree_sync.sync(feature, "dev", cherry_picks=[first, second])

    assert result.status == "conflict"
    assert result.before == result.after == before
    assert not (feature / "first.txt").exists()
    assert _run(feature, "status", "--porcelain") == ""
    assert not (feature / ".git" / "rebase-apply").exists()


def test_sandbox_push_protection_refuses_before_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing host protection refuses sandbox sync before any remote-transport invocation."""
    _origin, _primary, feature = _repository(tmp_path)
    sha = "a" * 40
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")
    monkeypatch.setenv("PATH", f"{tmp_path}:{Path('/usr/bin')}")

    with pytest.raises(worktree_sync.SyncError) as raised:
        worktree_sync.sync(feature, "dev", cherry_picks=[sha], dry_run=True)

    assert raised.value.exit_code == worktree_sync.EXIT_TRANSPORT
    assert "host-provisioned" in str(raised.value)


def test_sandbox_late_validation_failure_leaves_tree_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad second response prevents the already downloaded first patch from being applied."""
    _origin, primary, feature = _repository(tmp_path)
    _configure_sandbox(feature)
    (primary / "first.txt").write_text("first\n", encoding="utf-8")
    _run(primary, "add", "first.txt")
    _run(primary, "commit", "-m", "first patch")
    first = _run(primary, "rev-parse", "HEAD")
    second = "b" * 40
    before = _run(feature, "rev-parse", "HEAD")
    first_response = _patch_response(primary, first)
    _install_gh_stub(
        tmp_path,
        monkeypatch,
        {
            first: first_response,
            second: ({"sha": second, "parents": [{}, {}], "commit": {"message": "merge"}}, "bad patch"),
        },
    )
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")

    with pytest.raises(worktree_sync.SyncError) as raised:
        worktree_sync.sync(feature, "dev", cherry_picks=[first, second])

    assert raised.value.exit_code == worktree_sync.EXIT_TRANSPORT
    assert _run(feature, "rev-parse", "HEAD") == before
    assert not (feature / "first.txt").exists()
    assert _run(feature, "status", "--porcelain") == ""
