"""Shared-environment policy and real subprocess filesystem regression tests."""

from __future__ import annotations

import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Any
from unittest.mock import AsyncMock

import pytest

from parrot.flows.dev_loop import worktree_environment as policy
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
from parrot.flows.dev_loop.dispatchers.claude import ClaudeCodeDispatcher
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile, LLMCodeDispatchProfile


@pytest.fixture
def checkout(tmp_path: Path) -> tuple[Path, Path]:
    """Model a pool checkout and the primary repository's shared environment."""
    main = tmp_path / "main"
    git_dir = main / ".git"
    admin = git_dir / "worktrees" / "task-a2"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..\n")
    worktree = tmp_path / "pool" / "task-a2"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {admin}\n")
    env = main / ".venv"
    env.mkdir()
    (env / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (env / "editable.pth").write_text("original\n")
    (worktree / ".venv").symlink_to(env, target_is_directory=True)
    return worktree, env


def test_resolves_pool_and_shared_symlink(checkout: tuple[Path, Path]) -> None:
    worktree, env = checkout
    child = worktree / "src"
    child.mkdir()
    root, common = policy.repository_paths(child)
    assert root == worktree
    assert common == env.parent / ".git"
    assert env in policy.shared_environments(child)
    with pytest.raises(ValueError, match="must not mutate"):
        policy.validate_write_path(child, worktree / ".venv" / "editable.pth")


@pytest.mark.parametrize(
    "argv",
    [
        ["uv", "sync"],
        ["uv", "sync", "--frozen"],
        ["uv", "run", "pytest"],
        ["uv", "run", "--locked", "pytest"],
        ["uv", "add", "sample"],
        ["uv", "pip", "install", "-e", "."],
        ["uv", "pip", "uninstall", "sample"],
        ["uv", "--directory", "subdir", "sync"],
    ],
)
def test_rejects_implicit_environment_mutations(checkout: tuple[Path, Path], argv: list[str]) -> None:
    assert policy.command_policy_error(checkout[0], argv) == policy.POLICY_MESSAGE


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "tests"],
        ["uv", "run", "--no-sync", "pytest"],
        ["uv", "add", "--no-sync", "sample"],
        ["uv", "pip", "show", "sample"],
    ],
)
def test_allows_existing_tools_and_metadata_changes(checkout: tuple[Path, Path], argv: list[str]) -> None:
    assert policy.command_policy_error(checkout[0], argv) is None


def test_explicit_install_requires_local_environment(checkout: tuple[Path, Path]) -> None:
    worktree, _ = checkout
    local = worktree / ".task-venv"
    (local / "bin").mkdir(parents=True)
    (local / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (local / "bin" / "python").symlink_to(sys.executable)
    assert (
        policy.command_policy_error(worktree, ["uv", "pip", "install", "--python", ".task-venv/bin/python", "x"])
        is None
    )
    assert policy.command_policy_error(worktree, ["uv", "pip", "install", "--python", ".venv/bin/python", "x"])


def test_missing_bubblewrap_fails_closed(checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(policy.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="refusing unsandboxed"):
        policy.protected_argv(checkout[0], ["true"])
    response = policy.hook_response({"cwd": str(checkout[0]), "tool_name": "Bash", "tool_input": {"command": "true"}})
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_preserves_shell_text_and_other_fields(
    checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(policy.shutil, "which", lambda _: "/usr/bin/bwrap")
    original = {"command": "printf '%s' 'a; $(false)' > result.txt", "timeout": 1200, "description": "check"}
    response = policy.hook_response({"cwd": str(checkout[0]), "tool_name": "Bash", "tool_input": original})
    output = response["hookSpecificOutput"]
    assert "permissionDecision" not in output
    updated = output["updatedInput"]
    assert updated["timeout"] == original["timeout"]
    assert updated["description"] == original["description"]
    assert shlex.split(updated["command"])[-3:] == ["/bin/bash", "-c", original["command"]]


@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit", "NotebookEdit"])
def test_native_file_tools_deny_environment_aliases(checkout: tuple[Path, Path], tool: str) -> None:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    response = policy.hook_response(
        {
            "cwd": str(checkout[0]),
            "tool_name": tool,
            "tool_input": {key: ".venv/editable.pth"},
        }
    )
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.asyncio
async def test_dispatch_rejects_sync_before_launch(
    checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatcher = LLMCodeDispatcher(max_concurrent=1, redis_url="redis://unused", stream_ttl_seconds=1)
    launch = AsyncMock()
    monkeypatch.setattr(dispatcher, "_run_argv", launch)
    result = await dispatcher._tool_run_command(str(checkout[0]), {"argv": ["uv", "sync"]}, LLMCodeDispatchProfile())
    assert result["ok"] is False
    launch.assert_not_called()


@pytest.mark.parametrize(
    "method,args",
    [
        ("_tool_write_file", {"path": ".venv/editable.pth", "content": "bad"}),
        ("_tool_edit_file", {"path": ".venv/editable.pth", "old_string": "original", "new_string": "bad"}),
    ],
)
def test_dispatch_file_tools_deny_environment_aliases(
    checkout: tuple[Path, Path], method: str, args: dict[str, Any]
) -> None:
    dispatcher = LLMCodeDispatcher(max_concurrent=1, redis_url="redis://unused", stream_ttl_seconds=1)
    with pytest.raises(ValueError, match="must not mutate"):
        getattr(dispatcher, method)(str(checkout[0]), args, LLMCodeDispatchProfile())
    assert (checkout[1] / "editable.pth").read_text() == "original\n"


def _require_bubblewrap() -> None:
    """Skip kernel integration only when the execution host cannot run bwrap."""
    executable = shutil.which("bwrap")
    if executable is None:
        pytest.skip("Bubblewrap is not installed; fail-closed behavior tested separately")
    probe = subprocess.run([executable, "--ro-bind", "/", "/", "--", "true"], capture_output=True, timeout=10)
    if probe.returncode:
        pytest.skip(f"Host disallows Bubblewrap namespaces: {probe.stderr.decode()}")


@pytest.mark.asyncio
async def test_real_child_cannot_write_shared_pth_but_can_read_and_write_task(checkout: tuple[Path, Path]) -> None:
    _require_bubblewrap()
    worktree, env = checkout
    script = worktree / "probe.py"
    script.write_text(
        "from pathlib import Path\n"
        "import subprocess, sys\n"
        f"target = Path({str(env / 'editable.pth')!r})\n"
        "assert target.read_text() == 'original\\n'\n"
        "child = subprocess.run([sys.executable, '-c', "
        "'from pathlib import Path; import sys; Path(sys.argv[1]).write_text(\"corrupt\")', str(target)])\n"
        "assert child.returncode != 0\n"
        "Path('task-output.txt').write_text('ok')\n"
        "Path('/tmp/sdd-sandbox-probe').write_text('private')\n"
    )
    dispatcher = LLMCodeDispatcher(max_concurrent=1, redis_url="redis://unused", stream_ttl_seconds=1)
    result = await dispatcher._run_argv([sys.executable, str(script)], cwd=str(worktree), timeout=20)
    assert result["exit_code"] == 0, result
    assert (env / "editable.pth").read_text() == "original\n"
    assert (worktree / "task-output.txt").read_text() == "ok"


def test_real_git_commit_in_linked_worktree(tmp_path: Path) -> None:
    _require_bubblewrap()
    main = tmp_path / "main"
    main.mkdir()
    for argv in (
        ["git", "init"],
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
        ],
    ):
        subprocess.run(argv, cwd=main, capture_output=True, check=True)
    worktree = tmp_path / "task"
    subprocess.run(["git", "worktree", "add", "-b", "task", str(worktree)], cwd=main, capture_output=True, check=True)
    (worktree / "change.txt").write_text("test\n")
    for argv in (
        ["git", "add", "change.txt"],
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "task"],
    ):
        result = subprocess.run(policy.protected_argv(worktree, argv), capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr


def test_standalone_hook_denies_invalid_input() -> None:
    result = subprocess.run(
        [sys.executable, policy.__file__, "--hook"], input="{}", capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_rewrites_broad_pytest_before_sandbox(checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(policy.shutil, "which", lambda _: "/usr/bin/bwrap")
    monkeypatch.setattr(policy, "_scope_guard", lambda command, cwd: ("rewrite", "pytest tests/test_a.py -q"))
    response = policy.hook_response({"cwd": str(checkout[0]), "tool_name": "Bash", "tool_input": {"command": "pytest"}})
    updated = response["hookSpecificOutput"]["updatedInput"]
    assert shlex.split(updated["command"])[-3:] == ["/bin/bash", "-c", "pytest tests/test_a.py -q"]


def test_hook_blocks_with_guard_message(checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(policy.shutil, "which", lambda _: "/usr/bin/bwrap")
    monkeypatch.setattr(policy, "_scope_guard", lambda command, cwd: ("block", "no scoped tests"))
    response = policy.hook_response({"cwd": str(checkout[0]), "tool_name": "Bash", "tool_input": {"command": "pytest"}})
    output = response["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert "no scoped tests" in output["permissionDecisionReason"]
    assert "updatedInput" not in output


def test_scope_guard_import_error_allows(checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise() -> Any:
        raise ImportError("no kernel in this checkout")

    monkeypatch.setattr(policy, "_load_guard_bash", _raise)
    assert policy._scope_guard("pytest", checkout[0]) == ("allow", None)

    monkeypatch.setattr(policy.shutil, "which", lambda _: "/usr/bin/bwrap")
    response = policy.hook_response({"cwd": str(checkout[0]), "tool_name": "Bash", "tool_input": {"command": "pytest"}})
    output = response["hookSpecificOutput"]
    assert "permissionDecision" not in output
    assert shlex.split(output["updatedInput"]["command"])[-3:] == ["/bin/bash", "-c", "pytest"]


def test_standalone_loader_resolves_kernel_by_path() -> None:
    hook_dir = str(Path(policy.__file__).parent)
    code = (
        f"import sys; sys.path.insert(0, {hook_dir!r}); "
        "import worktree_environment as we; "
        "print(we._load_guard_bash().__module__)"
    )
    result = subprocess.run([sys.executable, "-S", "-c", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "test_scope.guard"


@pytest.mark.parametrize("subagent", ["sdd-worker", "sdd-coder"])
def test_programmatic_claude_protection_does_not_depend_on_project_settings(tmp_path: Path, subagent: str) -> None:
    """Programmatic prompts lose frontmatter, so protection must be injected."""
    dispatcher = ClaudeCodeDispatcher(max_concurrent=1, redis_url="redis://unused", stream_ttl_seconds=1)
    profile = ClaudeCodeDispatchProfile(subagent=subagent, setting_sources=[])
    options = dispatcher._resolve_run_options(profile, str(tmp_path))
    hook = json.loads(options.extra_args["settings"])["hooks"]["PreToolUse"][0]
    assert "Bash" in hook["matcher"]
    command = hook["hooks"][0]["command"]
    assert "worktree_environment.py" in command
    assert command.endswith(" || exit 2")


def test_real_native_hook_keeps_primary_environment_read_only(tmp_path: Path) -> None:
    """Even the worker's initial main-checkout Bash must protect its .venv."""
    _require_bubblewrap()
    (tmp_path / ".git").mkdir()
    environment = tmp_path / ".venv"
    environment.mkdir()
    (environment / "pyvenv.cfg").write_text("home = /usr/bin\n")
    target = environment / "editable.pth"
    target.write_text("original\n")
    command = "printf corrupt > .venv/editable.pth"
    response = policy.hook_response({"cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {"command": command}})
    wrapped = response["hookSpecificOutput"]["updatedInput"]["command"]
    result = subprocess.run(["/bin/bash", "-c", wrapped], capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert "Read-only file system" in result.stderr
    assert target.read_text() == "original\n"
