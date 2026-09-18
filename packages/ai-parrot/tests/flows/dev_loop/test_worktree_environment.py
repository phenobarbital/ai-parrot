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


def test_hook_rewrites_broad_pytest_before_sandbox(
    checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
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


def _registered_feature_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Model a feature worktree registered under the primary checkout's ``.claude/worktrees``."""
    main = tmp_path / "main"
    git_dir = main / ".git"
    admin = git_dir / "worktrees" / "feat-x"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..\n")
    worktree = main / ".claude" / "worktrees" / "feat-x"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {admin}\n")
    return main, worktree


def _writable_binds(argv: list[str]) -> list[Path]:
    return [Path(argv[index + 1]) for index, token in enumerate(argv) if token == "--bind"]


def test_feature_worktree_binds_primary_worktree_admin_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A worktree agent may administer sibling worktrees, but the rest of the primary checkout stays read-only."""
    monkeypatch.setattr(policy.shutil, "which", lambda name: "/usr/bin/bwrap")
    main, worktree = _registered_feature_worktree(tmp_path)
    binds = _writable_binds(policy.protected_argv(worktree, ["true"]))
    assert (main / ".claude" / "worktrees").resolve() in binds
    assert (main / ".git").resolve() in binds
    assert main.resolve() not in binds


def test_primary_checkout_has_no_extra_worktree_admin_bind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(policy.shutil, "which", lambda name: "/usr/bin/bwrap")
    main = tmp_path / "main"
    (main / ".git").mkdir(parents=True)
    (main / ".claude" / "worktrees").mkdir(parents=True)
    assert _writable_binds(policy.protected_argv(main, ["true"])) == [main.resolve()]


def test_linked_checkout_without_admin_dir_binds_nothing_extra(
    checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(policy.shutil, "which", lambda name: "/usr/bin/bwrap")
    worktree, env = checkout
    binds = _writable_binds(policy.protected_argv(worktree, ["true"]))
    assert binds == [worktree.resolve(), (env.parent / ".git").resolve()]


def test_real_feature_worktree_can_administer_worktrees_but_not_primary_checkout(tmp_path: Path) -> None:
    """`/sdd-done` run from inside a feature worktree needs `git worktree add/remove` under the primary checkout."""
    _require_bubblewrap()
    main = tmp_path / "main"
    main.mkdir()
    git = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid"]
    subprocess.run(["git", "init"], cwd=main, capture_output=True, check=True)
    subprocess.run([*git, "commit", "--allow-empty", "-m", "initial"], cwd=main, capture_output=True, check=True)
    admin_dir = main / ".claude" / "worktrees"
    admin_dir.mkdir(parents=True)
    feature = admin_dir / "feat-x"
    subprocess.run(["git", "worktree", "add", "-b", "feat-x", str(feature)], cwd=main, capture_output=True, check=True)

    def sandboxed(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(policy.protected_argv(feature, argv), capture_output=True, text=True, timeout=20)

    snapshot = admin_dir / "_ledger-snapshot"
    result = sandboxed(["git", "worktree", "add", "--detach", str(snapshot), "HEAD"])
    assert result.returncode == 0, result.stderr
    assert (snapshot / ".git").is_file()
    result = sandboxed(["git", "worktree", "remove", str(snapshot)])
    assert result.returncode == 0, result.stderr
    assert not snapshot.exists()

    # pytest's tmp_path lives under /tmp, which the sandbox replaces with a
    # private tmpfs, so only the host view proves the primary checkout stayed
    # read-only: the probe must never reach the real directory.
    sandboxed(["touch", str(main / "stray-file")])
    assert not (main / "stray-file").exists()

    result = sandboxed(["git", "worktree", "remove", str(feature)])
    assert result.returncode == 0, result.stderr
    assert not feature.exists()


# ---------------------------------------------------------------------------
# Hung-command guard: a sandboxed process that never exits must not keep bwrap
# (and the host's Bash tool) "running" forever.
# ---------------------------------------------------------------------------


def _sandboxed_argv(response: dict[str, Any]) -> list[str]:
    return shlex.split(response["hookSpecificOutput"]["updatedInput"]["command"])


def test_hook_bounds_command_with_tool_timeout(checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(policy.shutil, "which", lambda name: f"/usr/bin/{name}")
    response = policy.hook_response(
        {"cwd": str(checkout[0]), "tool_name": "Bash", "tool_input": {"command": "pytest -q x.py", "timeout": 90_000}}
    )
    argv = _sandboxed_argv(response)
    tail = argv[argv.index("--") + 1 :]
    assert tail == ["/usr/bin/timeout", "-k", "5", "90", "/bin/bash", "-c", "pytest -q x.py"]


def test_hook_default_timeout_matches_host_default(
    checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(policy.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.delenv("BASH_DEFAULT_TIMEOUT_MS", raising=False)
    response = policy.hook_response({"cwd": str(checkout[0]), "tool_name": "Bash", "tool_input": {"command": "true"}})
    argv = _sandboxed_argv(response)
    assert argv[argv.index("--") + 1 :][:4] == ["/usr/bin/timeout", "-k", "5", "120"]
    monkeypatch.setenv("BASH_DEFAULT_TIMEOUT_MS", "600000")
    response = policy.hook_response({"cwd": str(checkout[0]), "tool_name": "Bash", "tool_input": {"command": "true"}})
    argv = _sandboxed_argv(response)
    assert argv[argv.index("--") + 1 :][:4] == ["/usr/bin/timeout", "-k", "5", "600"]


def test_hook_leaves_background_commands_unbounded_without_explicit_timeout(
    checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(policy.shutil, "which", lambda name: f"/usr/bin/{name}")
    payload = {
        "cwd": str(checkout[0]),
        "tool_name": "Bash",
        "tool_input": {"command": "true", "run_in_background": True},
    }
    argv = _sandboxed_argv(policy.hook_response(payload))
    assert argv[argv.index("--") + 1 :] == ["/bin/bash", "-c", "true"]
    payload["tool_input"]["timeout"] = 30_000
    argv = _sandboxed_argv(policy.hook_response(payload))
    assert argv[argv.index("--") + 1 :][:4] == ["/usr/bin/timeout", "-k", "5", "30"]


def test_real_hung_sandboxed_process_is_killed_at_tool_timeout(tmp_path: Path) -> None:
    """A child that prints an error and then never exits must not outlive the tool timeout."""
    _require_bubblewrap()
    (tmp_path / ".git").mkdir()
    command = "echo 'sqlite3.OperationalError: no such column: 624' >&2; sleep 60"
    response = policy.hook_response(
        {"cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {"command": command, "timeout": 1_000}}
    )
    argv = _sandboxed_argv(response)
    result = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    assert result.returncode == 124, result
    assert "no such column: 624" in result.stderr
