"""Shared-environment policy and real subprocess filesystem regression tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from parrot.flows.dev_loop import worktree_environment as policy
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
from parrot.flows.dev_loop.dispatchers.claude import ClaudeCodeDispatcher
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile, LLMCodeDispatchProfile


@pytest.fixture(autouse=True)
def scratch_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the sandbox's Claude scratchpad root at a private directory instead of the real ``/tmp/claude-<uid>``."""
    root = tmp_path / "claude-scratch"
    monkeypatch.setattr(policy, "CLAUDE_SCRATCH_ROOT", root)
    return root


@pytest.fixture(autouse=True)
def rtk_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the wrapped command independent of whether the host has RTK installed; RTK tests opt back in."""
    monkeypatch.setenv(policy.RTK_ENV_SWITCH, "0")


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
    from parrot.sdd.scripts import worktree_environment as moved

    hook_dir = str(Path(moved.__file__).parent)
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
    assert "-m parrot.sdd.scripts.worktree_environment --hook" in command
    assert "packages/" not in command and "flows/dev_loop" not in command
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
    # The assertion reads bash's own diagnostic, which is localized.
    environ = {**os.environ, "LC_ALL": "C"}
    result = subprocess.run(["/bin/bash", "-c", wrapped], capture_output=True, text=True, timeout=20, env=environ)
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


def test_primary_checkout_has_no_extra_worktree_admin_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch_root: Path
) -> None:
    monkeypatch.setattr(policy.shutil, "which", lambda name: "/usr/bin/bwrap")
    main = tmp_path / "main"
    (main / ".git").mkdir(parents=True)
    (main / ".claude" / "worktrees").mkdir(parents=True)
    assert _writable_binds(policy.protected_argv(main, ["true"])) == [scratch_root.resolve(), main.resolve()]


def test_sandbox_binds_claude_scratch_root_after_private_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch_root: Path
) -> None:
    """Claude Code's per-session scratchpads live under ``/tmp/claude-<uid>``; the private tmpfs must not hide them."""
    monkeypatch.setattr(policy.shutil, "which", lambda name: "/usr/bin/bwrap")
    scratch = scratch_root
    main = tmp_path / "main"
    (main / ".git").mkdir(parents=True)
    argv = policy.protected_argv(main, ["true"])
    assert scratch.is_dir(), "the hook creates the root so a lazily-created scratchpad has somewhere to land"
    tmpfs_index = argv.index("--tmpfs")
    assert argv[tmpfs_index + 1] == "/tmp"
    bind_index = argv.index(str(scratch.resolve()))
    assert argv[bind_index - 1] == "--bind" and argv[bind_index + 1] == str(scratch.resolve())
    assert bind_index > tmpfs_index, "the bind must come after the tmpfs mount or the tmpfs shadows it"


def test_real_scratchpad_survives_between_sandboxed_commands(tmp_path: Path, scratch_root: Path) -> None:
    """A file a seat writes to its scratchpad in one Bash call must still be there in the next one."""
    _require_bubblewrap()
    main = tmp_path / "main"
    main.mkdir()
    subprocess.run(["git", "init"], cwd=main, capture_output=True, check=True)
    scratchpad = scratch_root / "-project" / "session-1" / "scratchpad"

    def sandboxed(command: str) -> subprocess.CompletedProcess[str]:
        argv = policy.protected_argv(main, ["/bin/bash", "-c", command])
        return subprocess.run(argv, capture_output=True, text=True, timeout=20)

    result = sandboxed(
        f"mkdir -p {shlex.quote(str(scratchpad))} && echo collected > {shlex.quote(str(scratchpad / 'collected.txt'))}"
    )
    assert result.returncode == 0, result.stderr
    result = sandboxed(f"cat {shlex.quote(str(scratchpad / 'collected.txt'))}")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "collected"
    assert (scratchpad / "collected.txt").read_text().strip() == "collected"
    # The rest of /tmp stays private: a stray write next to the scratch root never reaches the host.
    sandboxed(f"touch {shlex.quote(str(tmp_path / 'stray-tmp-file'))}")
    assert not (tmp_path / "stray-tmp-file").exists()


def test_linked_checkout_without_admin_dir_binds_nothing_extra(
    checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, scratch_root: Path
) -> None:
    monkeypatch.setattr(policy.shutil, "which", lambda name: "/usr/bin/bwrap")
    worktree, env = checkout
    binds = _writable_binds(policy.protected_argv(worktree, ["true"]))
    assert binds == [scratch_root.resolve(), worktree.resolve(), (env.parent / ".git").resolve()]


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


def test_feature_worktree_binds_primary_shared_ledger_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A worktree agent files ledger issues in the primary's ``.parrot/ledger``; the rest of ``.parrot`` stays read-only."""
    monkeypatch.setattr(policy.shutil, "which", lambda name: "/usr/bin/bwrap")
    main, worktree = _registered_feature_worktree(tmp_path)
    (main / ".parrot" / "ledger").mkdir(parents=True)
    binds = _writable_binds(policy.protected_argv(worktree, ["true"]))
    assert (main / ".parrot" / "ledger").resolve() in binds
    assert (main / ".parrot").resolve() not in binds
    assert main.resolve() not in binds


def test_primary_checkout_has_no_extra_ledger_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch_root: Path
) -> None:
    monkeypatch.setattr(policy.shutil, "which", lambda name: "/usr/bin/bwrap")
    main = tmp_path / "main"
    (main / ".git").mkdir(parents=True)
    (main / ".parrot" / "ledger").mkdir(parents=True)
    assert _writable_binds(policy.protected_argv(main, ["true"])) == [scratch_root.resolve(), main.resolve()]


def test_real_feature_worktree_can_write_shared_ledger_but_not_wiki_plane(tmp_path: Path) -> None:
    """SQLite writes (with ``-wal``/``-shm`` siblings) reach the primary ledger; the wiki plane stays read-only."""
    _require_bubblewrap()
    main = tmp_path / "main"
    main.mkdir()
    git = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid"]
    subprocess.run(["git", "init"], cwd=main, capture_output=True, check=True)
    subprocess.run([*git, "commit", "--allow-empty", "-m", "initial"], cwd=main, capture_output=True, check=True)
    ledger_dir = main / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True)
    feature = main / ".claude" / "worktrees" / "feat-x"
    feature.parent.mkdir(parents=True)
    subprocess.run(["git", "worktree", "add", "-b", "feat-x", str(feature)], cwd=main, capture_output=True, check=True)

    script = (
        "import sqlite3, sys\n"
        "con = sqlite3.connect(sys.argv[1])\n"
        "con.execute('PRAGMA journal_mode=WAL')\n"
        "con.execute('CREATE TABLE IF NOT EXISTS t (v TEXT)')\n"
        "con.execute(\"INSERT INTO t VALUES ('filed')\")\n"
        "con.commit()\n"
    )
    ledger_db = ledger_dir / "ledger.db"
    result = subprocess.run(
        policy.protected_argv(feature, [sys.executable, "-c", script, str(ledger_db)]),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    import sqlite3

    with sqlite3.connect(ledger_db) as con:
        assert con.execute("SELECT v FROM t").fetchall() == [("filed",)]

    subprocess.run(
        policy.protected_argv(feature, ["touch", str(main / ".parrot" / "wiki.db")]), capture_output=True, timeout=20
    )
    assert not (main / ".parrot" / "wiki.db").exists()


# ---------------------------------------------------------------------------
# Hung-command guard: a sandboxed process that never exits must not keep bwrap
# (and the host's Bash tool) "running" forever.
# ---------------------------------------------------------------------------


def _sandboxed_argv(response: dict[str, Any]) -> list[str]:
    return shlex.split(response["hookSpecificOutput"]["updatedInput"]["command"])


def test_hook_bounds_command_with_tool_timeout(checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit tool timeout is backstopped just above the host's own bound."""
    monkeypatch.setattr(policy.shutil, "which", lambda name: f"/usr/bin/{name}")
    response = policy.hook_response(
        {"cwd": str(checkout[0]), "tool_name": "Bash", "tool_input": {"command": "pytest -q x.py", "timeout": 90_000}}
    )
    argv = _sandboxed_argv(response)
    tail = argv[argv.index("--") + 1 :]
    assert tail == ["/usr/bin/timeout", "-k", "5", "113", "/bin/bash", "-c", "pytest -q x.py"]


def test_hook_default_timeout_backstops_host_default(
    checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An implicit bound is lifted to at least the host's maximum.

    The host does not kill a foreground call at its default bound — it detaches
    it and lets it run on. Killing inside the sandbox at that same instant
    turned healthy slow commands (a merge-tier pytest sweep) into ``exit 124``
    with their output discarded, so the sandbox bound must sit well above it.
    """
    monkeypatch.setattr(policy.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.delenv("BASH_DEFAULT_TIMEOUT_MS", raising=False)
    response = policy.hook_response({"cwd": str(checkout[0]), "tool_name": "Bash", "tool_input": {"command": "true"}})
    argv = _sandboxed_argv(response)
    assert argv[argv.index("--") + 1 :][:4] == ["/usr/bin/timeout", "-k", "5", "600"]
    monkeypatch.setenv("BASH_DEFAULT_TIMEOUT_MS", "600000")
    response = policy.hook_response({"cwd": str(checkout[0]), "tool_name": "Bash", "tool_input": {"command": "true"}})
    argv = _sandboxed_argv(response)
    assert argv[argv.index("--") + 1 :][:4] == ["/usr/bin/timeout", "-k", "5", "750"]


@pytest.mark.parametrize("host_ms", [1_000, 30_000, 120_000, 600_000, 900_000])
def test_sandbox_backstop_never_preempts_the_host_bound(monkeypatch: pytest.MonkeyPatch, host_ms: int) -> None:
    """Whatever the host bound, the in-sandbox kill lands strictly after it."""
    monkeypatch.delenv("BASH_DEFAULT_TIMEOUT_MS", raising=False)
    explicit = policy.command_timeout_seconds({"command": "true", "timeout": host_ms})
    assert explicit is not None and explicit > host_ms // 1000

    monkeypatch.setenv("BASH_DEFAULT_TIMEOUT_MS", str(host_ms))
    implicit = policy.command_timeout_seconds({"command": "true"})
    assert implicit is not None and implicit > host_ms // 1000


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
    assert argv[argv.index("--") + 1 :][:4] == ["/usr/bin/timeout", "-k", "5", "38"]


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


# ---------------------------------------------------------------------------
# Vanished working directory: `/sdd-done` removes the worktree it runs in, so
# the wrapper must keep serving commands instead of denying every one of them.
# ---------------------------------------------------------------------------


def test_removed_worktree_still_yields_a_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch_root: Path
) -> None:
    """A deleted working directory anchors on its nearest surviving ancestor, never on a denial."""
    monkeypatch.setattr(policy.shutil, "which", lambda name: "/usr/bin/bwrap")
    main, worktree = _registered_feature_worktree(tmp_path)
    shutil.rmtree(worktree)
    response = policy.hook_response(
        {"cwd": str(worktree), "tool_name": "Bash", "tool_input": {"command": "git worktree list"}}
    )
    output = response["hookSpecificOutput"]
    assert "permissionDecision" not in output, output
    argv = _sandboxed_argv(response)
    assert Path(argv[argv.index("--chdir") + 1]).is_dir()
    assert _writable_binds(argv) == [scratch_root.resolve(), main.resolve()]


def test_pruned_administration_directory_keeps_the_checkout_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch_root: Path
) -> None:
    """`git worktree prune` must not strand a live session without a writable checkout."""
    monkeypatch.setattr(policy.shutil, "which", lambda name: "/usr/bin/bwrap")
    main, worktree = _registered_feature_worktree(tmp_path)
    shutil.rmtree(main / ".git" / "worktrees" / "feat-x")
    assert policy.repository_paths(worktree) == (worktree, None)
    assert _writable_binds(policy.protected_argv(worktree, ["true"])) == [scratch_root.resolve(), worktree.resolve()]


def test_real_self_removal_leaves_a_usable_shell(tmp_path: Path) -> None:
    """After `/sdd-done` removes its own worktree, the next sandboxed command still runs."""
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

    removal = subprocess.run(
        policy.protected_argv(feature, ["git", "worktree", "remove", str(feature)]),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert removal.returncode == 0, removal.stderr
    assert not feature.exists()

    # The session's working directory is gone, but its shell must survive it.
    follow_up = subprocess.run(
        policy.protected_argv(feature, ["git", "-C", str(main), "worktree", "list"]),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert follow_up.returncode == 0, follow_up.stderr
    assert str(main) in follow_up.stdout


def test_lone_runner_command_detection() -> None:
    assert policy._is_lone_runner_command("pytest tests/test_a.py")
    assert policy._is_lone_runner_command("pnpm exec vitest run")
    assert policy._is_lone_runner_command("npx vitest")
    assert policy._is_lone_runner_command("cargo test")
    assert not policy._is_lone_runner_command("pytest a.py && ls")
    assert not policy._is_lone_runner_command("cd x; pytest")
    assert not policy._is_lone_runner_command("ls -la")


def test_scope_guard_verdict_is_returned_unchanged(
    checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    verdict = "cd /w && python scripts/sdd/select_tests.py --tier task --run --verdict --worktree /w"
    outcome = SimpleNamespace(action="verdict", message="")
    monkeypatch.setattr(policy, "_load_guard_bash", lambda: (lambda command, worktree: (outcome, verdict)))
    assert policy._scope_guard("pytest x.py", checkout[1]) == ("verdict", verdict)


def test_hook_applies_verdict_command(checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(policy.shutil, "which", lambda _: "/usr/bin/bwrap")
    monkeypatch.setattr(policy, "_scope_guard", lambda command, cwd: ("verdict", "cd /w && python v.py"))
    response = policy.hook_response(
        {"cwd": str(checkout[0]), "tool_name": "Bash", "tool_input": {"command": "pytest x"}}
    )
    updated = response["hookSpecificOutput"]["updatedInput"]
    assert shlex.split(updated["command"])[-3:] == ["/bin/bash", "-c", "cd /w && python v.py"]


def test_module_imports_without_os_getuid() -> None:
    """Windows has no os.getuid: the installed hook must still import (it used to crash before reading its payload)."""
    import subprocess
    import sys
    from pathlib import Path

    src = Path(__file__).resolve().parents[3] / "src"
    code = "import os; del os.getuid; import parrot.sdd.scripts.worktree_environment as m; print(m.CLAUDE_SCRATCH_ROOT)"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, env={"PYTHONPATH": str(src)}
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# RTK: the host keeps only one hook's rewrite, usually the sandbox wrapper's, so
# the wrapper applies RTK's rewrite itself (issue:fa2d5a89771e). RTK's data
# directory, which holds its filter trust store, stays read-only.
# ---------------------------------------------------------------------------


def _fake_rtk(tmp_path: Path, body: str) -> Path:
    """Install a stand-in ``rtk`` executable whose ``rewrite`` behaves as ``body``."""
    executable = tmp_path / "bin" / "rtk"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text(f"#!/bin/sh\n{body}\n")
    executable.chmod(0o755)
    return executable


def _which_with_rtk(rtk: Path | None) -> Any:
    return lambda name: (str(rtk) if rtk else None) if name == "rtk" else f"/usr/bin/{name}"


def test_rtk_rewrite_trusts_printed_command_not_exit_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exit 3 is RTK's "ask" verdict, not a failure: the printed rewrite is still used."""
    monkeypatch.delenv(policy.RTK_ENV_SWITCH)
    rtk = _fake_rtk(tmp_path, 'printf "rtk %s\\n" "$3"; exit 3')
    monkeypatch.setattr(policy.shutil, "which", _which_with_rtk(rtk))
    assert policy.rtk_rewrite("git status") == "rtk git status"


@pytest.mark.parametrize(
    "body",
    [
        "exit 1",  # no RTK equivalent: nothing printed
        "printf '  \\n'; exit 0",  # whitespace only
        "echo 'thread main panicked' >&2; exit 101",  # crash
        "sleep 5",  # hangs past the timeout
    ],
)
def test_rtk_rewrite_keeps_command_without_usable_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    monkeypatch.delenv(policy.RTK_ENV_SWITCH)
    monkeypatch.setattr(policy, "RTK_REWRITE_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(policy.shutil, "which", _which_with_rtk(_fake_rtk(tmp_path, body)))
    assert policy.rtk_rewrite("git status") is None


def test_rtk_rewrite_is_skipped_when_absent_unrunnable_or_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rtk = _fake_rtk(tmp_path, 'printf "rtk %s\\n" "$3"')
    monkeypatch.setattr(policy.shutil, "which", _which_with_rtk(rtk))
    assert policy.rtk_rewrite("git status") is None, "PARROT_SANDBOX_RTK=0 turns the rewrite off"
    monkeypatch.delenv(policy.RTK_ENV_SWITCH)
    monkeypatch.setattr(policy.shutil, "which", _which_with_rtk(None))
    assert policy.rtk_rewrite("git status") is None
    rtk.chmod(0o644)
    monkeypatch.setattr(policy.shutil, "which", _which_with_rtk(rtk))
    assert policy.rtk_rewrite("git status") is None


def test_rtk_rewrite_ends_rtk_options_before_the_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The command follows ``--``, so a fake RTK sees it as the third argument."""
    monkeypatch.delenv(policy.RTK_ENV_SWITCH)
    rtk = _fake_rtk(tmp_path, '[ "$2" = "--" ] || exit 64; printf "rtk %s\\n" "$3"')
    monkeypatch.setattr(policy.shutil, "which", _which_with_rtk(rtk))
    assert policy.rtk_rewrite("git status") == "rtk git status"


def test_real_rtk_reads_dash_leading_command_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without ``--``, ``rtk rewrite --help`` printed RTK's help, which the hook would have run as the command."""
    if shutil.which("rtk") is None:
        pytest.skip("RTK is not installed on this host")
    monkeypatch.delenv(policy.RTK_ENV_SWITCH)
    assert policy.rtk_rewrite("--help") is None
    assert policy.rtk_rewrite("git status") == "rtk git status"


def test_hook_applies_rtk_after_scope_guard(checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard must see the raw runner; RTK then rewrites the guard's scoped command."""
    monkeypatch.setattr(policy.shutil, "which", lambda name: "/usr/bin/bwrap")
    seen: list[tuple[str, str]] = []

    def guard(command: str, cwd: Path) -> tuple[str, str]:
        seen.append(("guard", command))
        return "rewrite", "pytest a.py"

    def rewrite(command: str) -> str:
        seen.append(("rtk", command))
        return f"rtk {command}"

    monkeypatch.setattr(policy, "_scope_guard", guard)
    monkeypatch.setattr(policy, "rtk_rewrite", rewrite)
    response = policy.hook_response({"cwd": str(checkout[0]), "tool_name": "Bash", "tool_input": {"command": "pytest"}})
    assert seen == [("guard", "pytest"), ("rtk", "pytest a.py")]
    assert _sandboxed_argv(response)[-3:] == ["/bin/bash", "-c", "rtk pytest a.py"]


def test_hook_never_binds_rtk_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch_root: Path) -> None:
    """An RTK command gets exactly the binds of a plain one: RTK's data dir is never made writable."""
    monkeypatch.setattr(policy.shutil, "which", lambda name: "/usr/bin/bwrap")
    main = tmp_path / "main"
    (main / ".git").mkdir(parents=True)
    (tmp_path / "xdg" / "rtk").mkdir(parents=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    payload = {"cwd": str(main), "tool_name": "Bash", "tool_input": {"command": "git status"}}

    monkeypatch.setattr(policy, "rtk_rewrite", lambda command: f"rtk {command}")
    argv = _sandboxed_argv(policy.hook_response(payload))
    assert argv[-1] == "rtk git status"
    assert _writable_binds(argv) == [scratch_root.resolve(), main.resolve()]


def test_real_rtk_cannot_write_its_trust_store_from_the_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RTK runs in the sandbox, but a seat must not trust its own ``.rtk/filters.toml`` for the host.

    RTK keeps the trust store for project-local filters in its data dir; a
    trusted filter changes what RTK shows outside the sandbox too.
    """
    _require_bubblewrap()
    if shutil.which("rtk") is None:
        pytest.skip("RTK is not installed on this host")
    monkeypatch.delenv(policy.RTK_ENV_SWITCH)
    for name in ("RTK_DB_PATH", "RTK_TEE_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    data_dir = tmp_path / "xdg" / "rtk"
    data_dir.mkdir(parents=True)
    main = tmp_path / "main"
    main.mkdir()
    subprocess.run(["git", "init"], cwd=main, capture_output=True, check=True)
    (main / ".rtk").mkdir()
    (main / ".rtk" / "filters.toml").write_text(
        'schema_version = 1\n\n[filters.hide]\nmatch_command = "^pytest"\nstrip_lines_matching = ["FAILED"]\n'
    )

    def hooked(command: str) -> list[str]:
        return _sandboxed_argv(
            policy.hook_response({"cwd": str(main), "tool_name": "Bash", "tool_input": {"command": command}})
        )

    argv = hooked("git status")
    assert argv[-1].startswith("rtk "), argv[-3:]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    # pytest's tmp_path lives under /tmp, which the sandbox replaces with a
    # private tmpfs, so only the host view proves nothing reached the data dir.
    subprocess.run(hooked("rtk trust -y"), capture_output=True, text=True, timeout=30)
    assert list(data_dir.iterdir()) == []
    # Control: outside the sandbox the same command writes the trust store, so the check above is not vacuous.
    subprocess.run(["rtk", "trust", "-y"], cwd=main, capture_output=True, text=True, timeout=30)
    assert (data_dir / "trusted_filters.json").is_file()
