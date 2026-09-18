"""Protect shared Python environments when executing SDD worktree commands.

This file deliberately uses only the standard library and can run directly as
a Claude hook, even when importing the rest of Parrot is unavailable.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
from typing import Any, Sequence

POLICY_MESSAGE = (
    "Worktree agents may read and execute the shared environment, but must not mutate it. "
    "Use existing tools directly or uv run --no-sync. For dependency changes, use a real "
    "task-local virtual environment with an explicit --python target, or ask the main-checkout "
    "operator for a controlled installation. Never repair shared .pth files from a task."
)


def repository_paths(cwd: Path) -> tuple[Path, Path | None]:
    """Find the checkout root and common Git directory, including pool worktrees."""
    cwd = cwd.resolve(strict=True)
    for root in (cwd, *cwd.parents):
        marker = root / ".git"
        if marker.is_dir():
            return root, marker.resolve()
        if marker.is_file():
            content = marker.read_text(encoding="utf-8").strip()
            if not content.startswith("gitdir: "):
                raise ValueError(f"Invalid Git worktree marker: {marker}")
            git_dir = (root / content.removeprefix("gitdir: ")).resolve(strict=True)
            common = git_dir / "commondir"
            if common.is_file():
                git_dir = (git_dir / common.read_text(encoding="utf-8").strip()).resolve(strict=True)
            return root, git_dir
    return cwd, None


def shared_environments(cwd: Path) -> tuple[Path, ...]:
    """Resolve environment symlinks so aliases receive the same protection."""
    root, git_dir = repository_paths(cwd)
    candidates = [Path(sys.prefix), root / ".venv"]
    if git_dir is not None:
        candidates.append(git_dir.parent / ".venv")
    for name in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
        if value := os.environ.get(name):
            candidates.append(root / value)
    environments = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if not (resolved / "pyvenv.cfg").is_file():
            continue
        # A real environment inside a linked task checkout is task-owned.
        is_task_local = git_dir is not None and git_dir.parent != root and resolved.is_relative_to(root)
        if not is_task_local:
            environments.add(resolved)
    return tuple(sorted(environments))


def validate_write_path(cwd: Path, path: Path) -> None:
    """Reject direct file-tool writes through aliases into shared environments."""
    target = path.resolve()
    if any(target == env or target.is_relative_to(env) for env in shared_environments(cwd)):
        raise ValueError(POLICY_MESSAGE)


def command_policy_error(cwd: Path, argv: Sequence[str]) -> str | None:
    """Give early feedback for package operations; filesystem mounts enforce safety."""
    if not argv:
        return "A command is required."
    command = Path(argv[0]).name
    if command != "uv":
        return None
    args = list(argv[1:])
    if args[:1] in (["--version"], ["version"], ["help"]):
        return None
    if args[:1] == ["run"] and "--no-sync" in args[1:]:
        return None
    if args[:1] in (["add"], ["remove"]) and "--no-sync" in args[1:]:
        return None
    if args[:2] in (["pip", "list"], ["pip", "show"], ["pip", "check"]):
        return None
    if args[:1] == ["venv"]:
        # The filesystem sandbox prevents targeting a shared environment.
        return None
    if args[:2] in (["pip", "install"], ["pip", "uninstall"], ["pip", "sync"]):
        for index, value in enumerate(args):
            target = value.split("=", 1)[1] if value.startswith("--python=") else None
            if value == "--python" and index + 1 < len(args):
                target = args[index + 1]
            if target:
                # Do not resolve the Python symlink itself: venv/bin/python
                # commonly points at the system interpreter.
                interpreter = Path(os.path.abspath(cwd / target))
                environment = interpreter.parent.parent.resolve()
                root, _ = repository_paths(cwd)
                if environment.is_relative_to(root) and (environment / "pyvenv.cfg").is_file():
                    if environment not in shared_environments(cwd):
                        return None
    return POLICY_MESSAGE


WORKTREE_ADMIN_DIR = Path(".claude") / "worktrees"


def worktree_admin_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]:
    """Return the primary checkout's worktree directory when ``root`` is a linked worktree.

    Linked worktrees (feature and pool checkouts) live under the primary
    checkout's ``.claude/worktrees``. ``/sdd-done`` run from inside one must
    create a throwaway ledger-snapshot worktree there and remove the feature
    worktree itself, and both operations write to that directory rather than
    to the worktree being executed in. The rest of the primary checkout is
    intentionally not returned so it stays read-only.

    Args:
        root: The checkout root resolved for the command's working directory.
        git_dir: The common Git directory, or ``None`` outside a repository.

    Returns:
        The existing admin directory to bind writable, or an empty tuple for
        the primary checkout (already writable) and for linked checkouts whose
        primary has no such directory.
    """
    if git_dir is None:
        return ()
    primary = git_dir.parent
    if primary == root:
        return ()
    admin_dir = (primary / WORKTREE_ADMIN_DIR).resolve()
    if not admin_dir.is_dir() or admin_dir.is_relative_to(root):
        return ()
    return (admin_dir,)


def protected_argv(cwd: Path, argv: Sequence[str]) -> list[str]:
    """Build a fail-closed Linux filesystem sandbox for a command and its children.

    Only the checkout, Git administration directory, the primary checkout's
    worktree directory (``.claude/worktrees``, so a worktree agent can run
    ``git worktree add/remove`` for ``/sdd-done``), and private temporary
    storage are writable. The rest of the primary checkout and existing shared
    environments remain read-only even when the checkout is the primary
    repository. No host chmod or mount changes are performed. Network
    isolation is outside this policy's scope.
    """
    if not argv:
        raise ValueError("A command is required.")
    executable = shutil.which("bwrap")
    if executable is None:
        raise RuntimeError("Bubblewrap (bwrap) is required for SDD commands; refusing unsandboxed execution.")
    root, git_dir = repository_paths(cwd)
    command = [
        executable,
        "--die-with-parent",
        "--unshare-pid",
        "--new-session",
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
    ]
    admin_dirs = worktree_admin_dirs(root, git_dir)
    for admin_dir in admin_dirs:
        command.extend(["--bind", str(admin_dir), str(admin_dir)])
    if not any(root.is_relative_to(admin_dir) for admin_dir in admin_dirs):
        # A checkout inside a bound admin directory is already writable; binding
        # it again would make it a mount point, and `git worktree remove` of the
        # current worktree would then fail to delete the directory (EBUSY).
        command.extend(["--bind", str(root), str(root)])
    if git_dir is not None and not git_dir.is_relative_to(root):
        command.extend(["--bind", str(git_dir), str(git_dir)])
    for environment in shared_environments(cwd):
        command.extend(["--ro-bind", str(environment), str(environment)])
    # Caches are disposable and must not write into the shared host cache.
    command.extend(["--setenv", "XDG_CACHE_HOME", "/tmp/cache", "--setenv", "UV_CACHE_DIR", "/tmp/uv-cache"])
    command.extend(["--setenv", "UV_NO_SYNC", "1", "--setenv", "PYTHONDONTWRITEBYTECODE", "1"])
    source_roots = sorted((root / "packages").glob("*/src"))
    if source_roots:
        python_path = os.pathsep.join(map(str, source_roots))
        if inherited := os.environ.get("PYTHONPATH"):
            python_path += os.pathsep + inherited
        command.extend(["--setenv", "PYTHONPATH", python_path])
    command.extend(["--chdir", str(cwd.resolve()), "--", *argv])
    return command


def _load_guard_bash() -> Any:
    """Import the stdlib-only test-scope guard without importing Parrot.

    Returns:
        The kernel's ``guard_bash`` callable.

    Raises:
        ImportError: The checkout serving this hook has no test-scope kernel.
    """
    if __package__:
        from .test_scope.guard import guard_bash
    else:  # run as a script: this file's directory is sys.path[0]
        from test_scope.guard import guard_bash
    return guard_bash


_COMPOUND_MARKERS = ("&&", "||", ";", "|")


def _is_lone_pytest(command: str) -> bool:
    """True when `command` is a single pytest/python invocation with no shell compounding."""
    stripped = command.strip()
    if any(marker in stripped for marker in _COMPOUND_MARKERS):
        return False
    try:
        argv = shlex.split(stripped)
    except ValueError:
        return False
    return bool(argv) and Path(argv[0]).name in {"pytest", "python", "python3"}


def _scope_guard(command: str, cwd: Path) -> tuple[str, str | None]:
    """Decide whether a native Bash command runs an over-broad pytest (FEAT-563).

    Args:
        command: The Bash command the seat issued.
        cwd: The hook's working directory.

    Returns:
        ``("allow", None)``, ``("rewrite", <command>)`` or ``("block", <message>)``.
        Import failures and guard errors always yield ``("allow", None)``.
    """
    try:
        guard_bash = _load_guard_bash()
        root, _common = repository_paths(cwd)
        outcome, rewritten = guard_bash(command, worktree=root)
    except Exception:  # noqa: BLE001 — the sandbox wrapper must never break
        return "allow", None
    if outcome.action == "block":
        return "block", outcome.message
    if outcome.action == "rewrite" and rewritten:
        # The kernel's rewritten command is root-relative; when the hook's cwd is a
        # different directory, a lone pytest invocation needs an explicit `cd` first
        # so the rewritten (repo-relative) paths still resolve (spec R2). A command
        # that already mixes its own `cd`/segments keeps its author's cwd handling.
        if root != cwd and _is_lone_pytest(command):
            rewritten = f"cd {shlex.quote(str(root))} && {rewritten}"
        return "rewrite", rewritten
    return "allow", None


HOST_DEFAULT_TIMEOUT_MS = 120_000
KILL_GRACE_SECONDS = 5


def command_timeout_seconds(tool_input: dict[str, Any]) -> int | None:
    """Resolve the wall-clock bound the sandboxed command must respect.

    The host kills a foreground Bash call at ``tool_input["timeout"]`` (or its
    default, ``BASH_DEFAULT_TIMEOUT_MS`` / 120 s). A process that prints an
    error and then never exits — an unclosed ``aiosqlite`` worker thread is the
    classic case — keeps Bubblewrap waiting on it, and the host's kill does not
    always reach through the sandbox. Enforcing the same bound *inside* the
    sandbox guarantees the call terminates either way.

    Args:
        tool_input: The native ``Bash`` tool input.

    Returns:
        The bound in whole seconds (at least 1), or ``None`` for a background
        command without an explicit timeout, which the host never bounds.
    """
    explicit = tool_input.get("timeout")
    if isinstance(explicit, (int, float)) and explicit > 0:
        return max(1, int(explicit // 1000))
    if tool_input.get("run_in_background"):
        return None
    default_ms = os.environ.get("BASH_DEFAULT_TIMEOUT_MS", "")
    try:
        milliseconds = int(default_ms) if default_ms else HOST_DEFAULT_TIMEOUT_MS
    except ValueError:
        milliseconds = HOST_DEFAULT_TIMEOUT_MS
    return max(1, milliseconds // 1000)


def bounded_shell_argv(command: str, tool_input: dict[str, Any]) -> list[str]:
    """Build the ``/bin/bash -c`` argv for ``command``, wrapped in ``timeout`` when bounded.

    ``timeout`` sends SIGTERM to the whole command group at the bound and SIGKILL
    ``KILL_GRACE_SECONDS`` later, so the sandbox's main child always exits and
    Bubblewrap tears the PID namespace down with it.

    Args:
        command: The shell text the seat issued (already scope-guarded).
        tool_input: The native ``Bash`` tool input, for the timeout fields.

    Returns:
        The argv to place after Bubblewrap's ``--`` separator.
    """
    argv = ["/bin/bash", "-c", command]
    seconds = command_timeout_seconds(tool_input)
    timeout_bin = shutil.which("timeout") if seconds is not None else None
    if timeout_bin is None:
        return argv
    return [timeout_bin, "-k", str(KILL_GRACE_SECONDS), str(seconds), *argv]


def hook_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap native Bash input and reject shared-environment file-tool writes."""
    cwd = Path(payload["cwd"])
    tool_input = payload["tool_input"]
    output: dict[str, Any] = {"hookEventName": "PreToolUse"}
    try:
        if payload["tool_name"] == "Bash":
            command = tool_input["command"]
            if not isinstance(command, str) or not command:
                raise ValueError("Bash command must be a non-empty string")
            action, value = _scope_guard(command, cwd)
            if action == "block":
                raise ValueError(value or "over-broad pytest blocked by the test-scope guard")
            if action == "rewrite" and value:
                command = value
            wrapped = protected_argv(cwd, bounded_shell_argv(command, tool_input))
            # Preserve timeout/background/description without granting approval
            # or overriding decisions from other hooks.
            output["updatedInput"] = {**tool_input, "command": shlex.join(wrapped)}
        else:
            path = tool_input.get("file_path") or tool_input.get("notebook_path")
            if not isinstance(path, str):
                raise ValueError("File tool requires a path")
            validate_write_path(cwd, cwd / path)
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        output.update(permissionDecision="deny", permissionDecisionReason=str(exc))
    return {"hookSpecificOutput": output}


def main() -> None:
    """Serve a native PreToolUse hook without importing application dependencies."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hook", action="store_true", required=True)
    parser.parse_args()
    try:
        result = hook_response(json.load(sys.stdin))
    except Exception as exc:
        # A nonzero hook failure normally fails open. Emit an explicit denial.
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"Shared-environment guard failed: {exc}",
            }
        }
    sys.stdout.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
