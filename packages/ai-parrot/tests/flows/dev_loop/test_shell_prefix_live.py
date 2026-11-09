"""Opt-in live qualification of the legacy Claude shell prefix."""

from __future__ import annotations

import os
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from parrot.sdd.scripts import native_claude_sandbox as native

pytestmark = pytest.mark.skipif(
    os.environ.get("PARROT_TEST_REAL_LLM") != "1", reason="live provider probes require PARROT_TEST_REAL_LLM=1"
)


def _run_git(arguments: list[str], cwd: Path) -> None:
    """Run fixture-only Git setup and show its diagnostic if it fails."""
    completed = subprocess.run(arguments, cwd=cwd, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr


def _write_executable(path: Path, contents: str) -> None:
    """Write an executable shell fixture outside the session worktree."""
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o700)


def test_legacy_prefix_live_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep Bash sandboxed while configured hook and MCP processes pass through the prefix."""
    if shutil.which("claude") is None or shutil.which("bwrap") is None:
        pytest.skip("live legacy qualification requires claude and bwrap")

    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(["git", "init", "-q"], repo)
    _run_git(["git", "config", "user.email", "qualification@example.invalid"], repo)
    _run_git(["git", "config", "user.name", "Shell prefix qualification"], repo)
    (repo / "README.md").write_text("qualification\n", encoding="utf-8")
    _run_git(["git", "add", "README.md"], repo)
    _run_git(["git", "commit", "-qm", "fixture"], repo)

    hook_token = tmp_path / "hook-token"
    mcp_token = tmp_path / "mcp-token"
    outside = tmp_path / "outside-bound-roots"
    hook = tmp_path / "hook"
    mcp = tmp_path / "mcp"
    _write_executable(hook, f'#!/bin/sh\nprintf "%s" "$PARROT_SDD_SHELL_PREFIX_TOKEN" > {hook_token!s}\n')
    _write_executable(
        mcp,
        f'#!/bin/sh\nprintf "%s" "$PARROT_SDD_SHELL_PREFIX_TOKEN" > {mcp_token!s}\nexec sleep 20\n',
    )
    claude_dir = repo / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(
        '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"' + str(hook) + '"}]}]}}',
        encoding="utf-8",
    )
    (repo / ".mcp.json").write_text(
        '{"mcpServers":{"qualification":{"command":"' + str(mcp) + '","args":[]}}}', encoding="utf-8"
    )
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    environment = {**os.environ, **native.prepare_shell_prefix(repo, {}, "legacy", rtk=True)}
    prompt = f"Use Bash once to run `touch {outside}`. Report whether the command succeeded."
    completed = subprocess.run(
        ["claude", "-p", prompt, "--model", "haiku", "--setting-sources", "local", "--allowedTools", "Bash"],
        cwd=repo,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert not outside.exists()
    policy_bytes = Path(environment["PARROT_SDD_SHELL_PREFIX_POLICY"]).read_bytes()
    expected_token = hashlib.sha256(policy_bytes).hexdigest()
    assert hook_token.read_text(encoding="utf-8") == expected_token
    assert mcp_token.read_text(encoding="utf-8") == expected_token
