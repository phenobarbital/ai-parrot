"""Tests for the host-prepared ``parrot devloop launch-worker`` command."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
from click.testing import CliRunner

from parrot.cli.devloop import devloop
from parrot.flows.dev_loop import feature_launcher as launcher


def _result(argv: list[str], code: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    """Build a scripted subprocess result."""
    return subprocess.CompletedProcess(argv, code, stdout, stderr)


def _primary(tmp_path: Path) -> Path:
    """Create a minimal primary checkout with one feature index."""
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    index = primary / "sdd" / "tasks" / "index" / "sandbox.json"
    index.parent.mkdir(parents=True)
    index.write_text(
        json.dumps({"feature": "sandbox", "feature_id": "FEAT-768", "spec": "sdd/specs/sandbox.md"}),
        encoding="utf-8",
    )
    return primary


def test_resolve_feature_is_case_insensitive_and_skips_orphans(tmp_path: Path) -> None:
    """Feature ids and slugs are both valid case-insensitive launch keys."""
    primary = _primary(tmp_path)
    (primary / "sdd" / "tasks" / "index" / "_orphans.json").write_text("{}", encoding="utf-8")
    ref = launcher.resolve_feature(primary, "feat-768")
    assert ref.feature_id == "FEAT-768"
    assert ref.slug == "sandbox"
    assert ref.index == "sdd/tasks/index/sandbox.json"


def test_resolve_feature_rejects_missing_or_ambiguous_keys(tmp_path: Path) -> None:
    """A launch key must identify exactly one feature index."""
    primary = _primary(tmp_path)
    with pytest.raises(launcher.LaunchError) as missing:
        launcher.resolve_feature(primary, "FEAT-999")
    assert missing.value.exit_code == 2
    duplicate = primary / "sdd" / "tasks" / "index" / "duplicate.json"
    duplicate.write_text(json.dumps({"feature": "other", "feature_id": "FEAT-768", "spec": "x"}), encoding="utf-8")
    with pytest.raises(launcher.LaunchError) as ambiguous:
        launcher.resolve_feature(primary, "FEAT-768")
    assert ambiguous.value.exit_code == 2


def test_prepare_upstream_divergence_never_mutates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Divergence is reported for reconciliation rather than merged or pushed."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    calls: list[list[str]] = []

    def fake_run(argv: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        values = {
            ("rev-parse", "--abbrev-ref", "HEAD"): "feature\n",
            ("ls-remote", "--heads", "origin", "feature"): "remote feature\n",
            ("rev-parse", "HEAD"): "local\n",
            ("rev-parse", "origin/feature"): "remote\n",
        }
        tail = tuple(argv[1:])
        if tail[:3] == ("merge-base", "--is-ancestor", "local"):
            return _result(argv, 1)
        if tail[:3] == ("merge-base", "--is-ancestor", "remote"):
            return _result(argv, 1)
        return _result(argv, stdout=values.get(tail, ""))

    monkeypatch.setattr(launcher, "_run", fake_run)
    with pytest.raises(launcher.LaunchError) as exc:
        launcher.prepare_upstream(worktree)
    assert exc.value.exit_code == 2
    assert not any(command[1] in {"merge", "push"} for command in calls)


def test_launch_non_tmux_passes_worktree_and_worker_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Normal launch performs host prep then delegates in the provisioned worktree."""
    primary = _primary(tmp_path)
    worktree = tmp_path / "feature"
    worktree.mkdir()
    captured: dict[str, object] = {}
    monkeypatch.chdir(primary)
    monkeypatch.setattr(launcher, "ensure_feature_worktree", lambda primary, ref: worktree)
    monkeypatch.setattr(launcher, "prepare_upstream", lambda path: "launch-worker: ready")
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: False)
    monkeypatch.setattr(
        launcher.native_claude_sandbox,
        "launch_worker",
        lambda argv, **kwargs: captured.update(argv=argv, **kwargs) or 0,
    )
    assert launcher.launch("sandbox", tmux=False, detach=False, sandbox="legacy", allowed_domains=("api.example.com",), no_upstream=False, claude_args=("--", "--verbose")) == 0
    assert captured["cwd"] == worktree
    assert captured["initial_prompt"] == "run FEAT-768"
    assert captured["argv"] == ["--sandbox-allow-domain", "api.example.com", "--", "--verbose"]


def test_tmux_new_session_carries_environment_and_detaches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Detached tmux workers receive the preparation environment explicitly."""
    primary = _primary(tmp_path)
    worktree = tmp_path / "feature"
    worktree.mkdir()
    calls: list[list[str]] = []
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PARROT_SDD_EXTRA", "yes")
    monkeypatch.setattr(launcher, "ensure_feature_worktree", lambda primary, ref: worktree)
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: False)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/tmux" if name == "tmux" else None)
    monkeypatch.setattr(launcher.native_claude_sandbox, "sandbox_platform", lambda: "linux")
    monkeypatch.setattr(launcher, "_run", lambda argv, *, cwd: calls.append(argv) or _result(argv))
    assert launcher.launch("FEAT-768", tmux=True, detach=True, sandbox="legacy", allowed_domains=(), no_upstream=True, claude_args=()) == 0
    command = calls[0]
    assert command[:8] == ["tmux", "new-session", "-d", "-s", "sdd-FEAT-768", "-c", str(worktree), "-e"]
    assert "PARROT_SDD_SANDBOX_MODE=legacy" in command
    assert "PARROT_SDD_EXTRA=yes" in command


def test_click_command_maps_launch_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lazy Click surface returns the launcher error code and diagnostic."""
    monkeypatch.setattr(launcher, "launch", lambda *args, **kwargs: (_ for _ in ()).throw(launcher.LaunchError(2, "bad key")))
    result = CliRunner().invoke(devloop, ["launch-worker", "missing"])
    assert result.exit_code == 2
    assert "launch-worker: bad key" in result.output
