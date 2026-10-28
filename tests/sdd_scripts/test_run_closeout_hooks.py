"""Tests for the closeout-hook dispatcher CLI (FEAT-764)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts.sdd import run_closeout_hooks
from scripts.sdd.closeout_hooks_config import HookContext


@pytest.fixture
def context_path(tmp_path: Path) -> Path:
    """Write a context file whose worktree is the temporary repository root."""
    path = tmp_path / "context.json"
    path.write_text(
        HookContext(
            feat_id="FEAT-764",
            spec_path=str(tmp_path / "spec.md"),
            branch="feat-FEAT-764",
            base_branch="dev",
            worktree=str(tmp_path),
        ).model_dump_json(),
        encoding="utf-8",
    )
    return path


def _config(root: Path, text: str) -> None:
    """Create a scoped hooks configuration."""
    config_dir = root / ".parrot"
    config_dir.mkdir()
    (config_dir / "sdd_hooks.toml").write_text(text, encoding="utf-8")


def _run(root: Path, context: Path, *extra: str) -> int:
    """Invoke the dispatcher with its standard event, root, and context."""
    return run_closeout_hooks.main(["--event", "pre_pr", "--root", str(root), "--context", str(context), *extra])


def test_no_config_exit_0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, context_path: Path) -> None:
    """An absent configuration produces an empty successful outcome."""
    monkeypatch.setenv("SDD_HOOKS_ARTIFACT_ROOT", str(tmp_path / "art"))
    assert _run(tmp_path, context_path) == 0
    outcome = json.loads((tmp_path / "art" / "FEAT-764" / "pre_pr.json").read_text())
    assert outcome["results"] == []
    assert outcome["evidence_md"] == ""


def test_malformed_config_exit_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, context_path: Path) -> None:
    """Malformed configuration fails closed with the usage exit code."""
    monkeypatch.setenv("SDD_HOOKS_ARTIFACT_ROOT", str(tmp_path / "art"))
    _config(tmp_path, "[hooks")
    assert _run(tmp_path, context_path) == 2


def test_command_pass_and_env_vars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, context_path: Path) -> None:
    """Command hooks receive their documented environment variables."""
    monkeypatch.setenv("SDD_HOOKS_ARTIFACT_ROOT", str(tmp_path / "art"))
    _config(
        tmp_path,
        f"""[[hooks.pre_pr]]
name = "command"
kind = "command"
run = "{sys.executable} -c \\\"import os, pathlib; pathlib.Path(os.environ['SDD_HOOK_ARTIFACT_DIR']).joinpath('x.txt').write_text(os.environ['SDD_FEAT_ID'])\\\""
artifacts = "*.txt"
""",
    )
    assert _run(tmp_path, context_path) == 0
    assert (tmp_path / "art" / "FEAT-764" / "command" / "x.txt").read_text() == "FEAT-764"


@pytest.mark.parametrize("blocking, expected", [("true", 1), ("false", 0)])
def test_command_fail_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, context_path: Path, blocking: str, expected: int
) -> None:
    """Only blocking pre-PR command failures stop closeout."""
    monkeypatch.setenv("SDD_HOOKS_ARTIFACT_ROOT", str(tmp_path / "art"))
    _config(
        tmp_path,
        f"""[[hooks.pre_pr]]
name = "fail"
kind = "command"
run = "{sys.executable} -c \\\"raise SystemExit(4)\\\""
blocking = {blocking}
""",
    )
    assert _run(tmp_path, context_path) == expected


def test_command_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, context_path: Path) -> None:
    """A timed-out command is recorded as a timeout and blocks when configured."""
    monkeypatch.setenv("SDD_HOOKS_ARTIFACT_ROOT", str(tmp_path / "art"))
    _config(
        tmp_path,
        f"""[[hooks.pre_pr]]
name = "slow"
kind = "command"
run = "{sys.executable} -c \\\"import time; time.sleep(2)\\\""
timeout_s = 1
blocking = true
""",
    )
    assert _run(tmp_path, context_path) == 1
    outcome = json.loads((tmp_path / "art" / "FEAT-764" / "pre_pr.json").read_text())
    assert outcome["results"][0]["status"] == "timeout"


def test_dry_run_runs_pre_pr_skips_post_pr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, context_path: Path) -> None:
    """Dry runs execute pre-PR hooks but skip all post-PR hooks."""
    monkeypatch.setenv("SDD_HOOKS_ARTIFACT_ROOT", str(tmp_path / "art"))
    _config(
        tmp_path,
        f"""[[hooks.pre_pr]]
name = "pre"
kind = "command"
run = "{sys.executable} -c \\\"raise SystemExit(0)\\\""

[[hooks.post_pr]]
name = "post"
kind = "command"
run = "{sys.executable} -c \\\"raise SystemExit(9)\\\""
""",
    )
    assert _run(tmp_path, context_path, "--dry-run") == 0
    assert (
        run_closeout_hooks.main(
            ["--event", "post_pr", "--root", str(tmp_path), "--context", str(context_path), "--dry-run"]
        )
        == 0
    )
    outcome = json.loads((tmp_path / "art" / "FEAT-764" / "post_pr.json").read_text())
    assert outcome["results"][0]["status"] == "skipped"


def test_agent_pending_exit_3_then_record_finalize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, context_path: Path
) -> None:
    """Agent hooks remain pending until a host record is finalized."""
    monkeypatch.setenv("SDD_HOOKS_ARTIFACT_ROOT", str(tmp_path / "art"))
    _config(
        tmp_path,
        """[[hooks.pre_pr]]
name = "agent"
kind = "agent"
agent = "reviewer"
prompt = "Review {feat_id} in {artifact_dir}"
blocking = true
""",
    )
    assert _run(tmp_path, context_path) == 3
    record_args = [
        "--event",
        "pre_pr",
        "--root",
        str(tmp_path),
        "--feat-id",
        "FEAT-764",
        "--record",
        "agent",
        "--status",
        "pass",
    ]
    assert run_closeout_hooks.main(record_args) == 0
    assert (
        run_closeout_hooks.main(["--event", "pre_pr", "--root", str(tmp_path), "--feat-id", "FEAT-764", "--finalize"])
        == 0
    )


def test_finalize_unrecorded_pending_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, context_path: Path) -> None:
    """Finalizing an unrecorded blocking agent hook fails the pre-PR event."""
    monkeypatch.setenv("SDD_HOOKS_ARTIFACT_ROOT", str(tmp_path / "art"))
    _config(
        tmp_path,
        """[[hooks.pre_pr]]
name = "agent"
kind = "agent"
agent = "reviewer"
prompt = "Review {feat_id}"
blocking = true
""",
    )
    assert _run(tmp_path, context_path) == 3
    assert (
        run_closeout_hooks.main(["--event", "pre_pr", "--root", str(tmp_path), "--feat-id", "FEAT-764", "--finalize"])
        == 1
    )


def test_artifacts_globbed_and_in_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, context_path: Path) -> None:
    """Configured artifact paths are absolute and included in evidence markdown."""
    monkeypatch.setenv("SDD_HOOKS_ARTIFACT_ROOT", str(tmp_path / "art"))
    _config(
        tmp_path,
        f"""[[hooks.pre_pr]]
name = "evidence"
kind = "command"
run = "{sys.executable} -c \\\"import os, pathlib; pathlib.Path(os.environ['SDD_HOOK_ARTIFACT_DIR']).joinpath('evidence.txt').write_text('ok')\\\""
artifacts = "*.txt"
""",
    )
    assert _run(tmp_path, context_path) == 0
    outcome = json.loads((tmp_path / "art" / "FEAT-764" / "pre_pr.json").read_text())
    artifact = outcome["results"][0]["artifacts"][0]
    assert Path(artifact).is_absolute()
    assert artifact in outcome["evidence_md"]


def test_builtin_dispatch_uses_run_builtin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, context_path: Path) -> None:
    """Builtin hooks call the shared builtin dispatcher."""
    monkeypatch.setenv("SDD_HOOKS_ARTIFACT_ROOT", str(tmp_path / "art"))
    _config(tmp_path, '[[hooks.pre_pr]]\nname = "builtin"\nkind = "builtin"\nbuiltin = "telegram.send"')
    called: list[str] = []

    def fake_builtin(hook, context, artifact_dir):
        called.append(hook.name)
        return run_closeout_hooks.HookResult(
            name=hook.name, kind=hook.kind, status="pass", blocking=hook.blocking, summary="fake"
        )

    monkeypatch.setattr(run_closeout_hooks, "run_builtin", fake_builtin)
    assert _run(tmp_path, context_path) == 0
    assert called == ["builtin"]


def test_end_to_end_pre_pr_with_agent_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, context_path: Path
) -> None:
    """A real command and agent record complete the full pre-PR protocol."""
    monkeypatch.setenv("SDD_HOOKS_ARTIFACT_ROOT", str(tmp_path / "art"))
    _config(
        tmp_path,
        f"""[[hooks.pre_pr]]
name = "command"
kind = "command"
run = "{sys.executable} -c \\\"raise SystemExit(0)\\\""

[[hooks.pre_pr]]
name = "agent"
kind = "agent"
agent = "reviewer"
prompt = "Review {{feat_id}}"
""",
    )
    assert _run(tmp_path, context_path) == 3
    assert (
        run_closeout_hooks.main(
            [
                "--event",
                "pre_pr",
                "--root",
                str(tmp_path),
                "--feat-id",
                "FEAT-764",
                "--record",
                "agent",
                "--status",
                "pass",
            ]
        )
        == 0
    )
    assert (
        run_closeout_hooks.main(["--event", "pre_pr", "--root", str(tmp_path), "--feat-id", "FEAT-764", "--finalize"])
        == 0
    )
