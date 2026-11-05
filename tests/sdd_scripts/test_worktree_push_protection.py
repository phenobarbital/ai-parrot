"""Real temporary Git tests for host-provisioned sandbox push protection (FEAT-813)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from parrot.sdd.scripts import worktree_push_protection as protection
from parrot.sdd.scripts import worktree_sync


def _run(path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run Git in a disposable repository."""
    return subprocess.run(["git", "-C", str(path), *args], text=True, capture_output=True, check=check)


def _out(path: Path, *args: str) -> str:
    return _run(path, *args).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    """Bare origin, a primary clone and two linked worktrees (feature, sibling)."""
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    origin = tmp_path / "origin.git"
    primary = tmp_path / "primary"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(origin), str(primary)], check=True, capture_output=True)
    _run(primary, "config", "user.email", "test@example.invalid")
    _run(primary, "config", "user.name", "Protection Test")
    (primary / "file.txt").write_text("base\n", encoding="utf-8")
    _run(primary, "add", "file.txt")
    _run(primary, "commit", "-m", "initial")
    _run(primary, "branch", "-M", "dev")
    _run(primary, "push", "-u", "origin", "dev")
    feature = tmp_path / "feature"
    sibling = tmp_path / "sibling"
    _run(primary, "worktree", "add", "-b", "feat-FEAT-999-x", str(feature), "dev")
    _run(primary, "worktree", "add", "-b", "feat-FEAT-998-y", str(sibling), "dev")
    return primary, feature, sibling


def _pushurls(path: Path) -> list[str]:
    output = _run(path, "config", "--get-all", "remote.origin.pushurl", check=False).stdout
    return [line for line in output.splitlines() if line]


def test_enable_then_disable_round_trip(repo: tuple[Path, Path, Path]) -> None:
    """Enable satisfies the sandbox check without touching siblings; disable restores pushing."""
    primary, feature, sibling = repo

    assert protection.enable(feature) == "push protection enabled"

    assert worktree_sync.push_protection_ok(feature)
    worktree_sync._check_sandbox_push_protection(feature)
    assert _pushurls(primary) == []
    assert _pushurls(sibling) == []
    assert _run(feature, "push", "origin", "feat-FEAT-999-x", check=False).returncode != 0

    assert protection.disable(feature) == "push protection disabled"

    assert not worktree_sync.push_protection_ok(feature)
    with pytest.raises(worktree_sync.SyncError):
        worktree_sync._check_sandbox_push_protection(feature)
    assert _run(feature, "push", "origin", "feat-FEAT-999-x", check=False).returncode == 0


def test_enable_and_disable_are_idempotent(repo: tuple[Path, Path, Path]) -> None:
    _primary, feature, _sibling = repo
    protection.enable(feature)
    assert protection.enable(feature) == "push protection already enabled"
    assert _pushurls(feature) == ["no_push"]
    protection.disable(feature)
    assert protection.disable(feature) == "push protection not enabled"


def test_disable_never_protected_is_noop(repo: tuple[Path, Path, Path]) -> None:
    _primary, feature, _sibling = repo
    assert protection.disable(feature) == "push protection not enabled"
    assert _out(feature, "config", "--get", "remote.origin.url")


@pytest.mark.parametrize(
    ("key", "value", "needle"),
    [
        ("core.worktree", "/elsewhere", "core.worktree"),
        ("core.bare", "true", "core.bare"),
        ("remote.origin.pushurl", "git@example.invalid:x/y.git", "remote.origin.pushurl"),
    ],
)
def test_enable_refuses_unsafe_common_config(repo: tuple[Path, Path, Path], key: str, value: str, needle: str) -> None:
    """Common settings that need the manual migration refuse before anything is written."""
    primary, feature, _sibling = repo
    common = primary / ".git" / "config"
    _run(primary, "config", "--file", str(common), key, value)

    with pytest.raises(worktree_sync.SyncError) as raised:
        protection.enable(feature)

    assert raised.value.exit_code == worktree_sync.EXIT_TARGET
    assert needle in str(raised.value)
    assert _run(primary, "config", "--file", str(common), "extensions.worktreeConfig", check=False).returncode != 0


def test_primary_checkout_is_refused(repo: tuple[Path, Path, Path]) -> None:
    primary, _feature, _sibling = repo
    with pytest.raises(worktree_sync.SyncError) as raised:
        protection.enable(primary)
    assert raised.value.exit_code == worktree_sync.EXIT_TARGET
    assert "primary checkout" in str(raised.value)


@pytest.mark.parametrize("action", [protection.enable, protection.disable])
def test_sandbox_refuses_enable_and_disable(
    repo: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch, action: object
) -> None:
    _primary, feature, _sibling = repo
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")
    with pytest.raises(worktree_sync.SyncError) as raised:
        action(feature)  # type: ignore[operator]
    assert raised.value.exit_code == worktree_sync.EXIT_TRANSPORT
    assert _pushurls(feature) == []


def test_main_json_status(
    repo: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI resolves a path target and reports protection as JSON."""
    _primary, feature, _sibling = repo
    monkeypatch.setattr(protection, "resolve_target", lambda target: Path(target).resolve())

    assert protection.main(["enable", str(feature), "--json"]) == 0
    enabled = json.loads(capsys.readouterr().out)
    assert enabled["protected"] is True
    assert protection.main(["status", str(feature), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["message"] == "protected"
    assert protection.main(["disable", str(feature), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["protected"] is False
