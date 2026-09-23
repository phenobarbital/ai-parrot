"""Protect shared Python environments when executing SDD worktree commands.

This file deliberately uses only the standard library and can run directly as
a Claude hook, even when importing the rest of Parrot is unavailable.
"""

from __future__ import annotations

import argparse
import json
import math
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


def existing_directory(path: Path) -> Path:
    """Resolve ``path``, falling back to its nearest existing ancestor.

    ``/sdd-done`` ends by removing the very worktree it runs in, and
    ``git worktree prune`` can drop an administration directory underneath a
    live session. Resolving strictly raises there, and because every native
    Bash call is wrapped by this module, a single raise denies *every*
    subsequent command — the session loses its own shell and cannot even
    ``cd`` back to the primary checkout. Anchoring on the nearest surviving
    ancestor keeps the sandbox on a real directory instead: for a removed
    worktree that is the primary checkout's ``.claude/worktrees``, so the next
    command lands back inside the primary checkout.

    Args:
        path: The directory to resolve, which may no longer exist.

    Returns:
        The resolved directory, or the closest ancestor that still exists.
    """
    candidate = Path(os.path.abspath(path))
    for parent in (candidate, *candidate.parents):
        if parent.is_dir():
            return parent.resolve()
    return Path(candidate.anchor or os.sep)


def repository_paths(cwd: Path) -> tuple[Path, Path | None]:
    """Find the checkout root and common Git directory, including pool worktrees."""
    cwd = existing_directory(cwd)
    for root in (cwd, *cwd.parents):
        marker = root / ".git"
        if marker.is_dir():
            return root, marker.resolve()
        if marker.is_file():
            content = marker.read_text(encoding="utf-8").strip()
            if not content.startswith("gitdir: "):
                raise ValueError(f"Invalid Git worktree marker: {marker}")
            git_dir = Path(os.path.abspath(root / content.removeprefix("gitdir: ")))
            common = git_dir / "commondir"
            if common.is_file():
                git_dir = Path(os.path.abspath(git_dir / common.read_text(encoding="utf-8").strip()))
            # A pruned administration directory leaves the checkout orphaned:
            # keep it writable rather than denying the command outright.
            return root, git_dir.resolve() if git_dir.is_dir() else None
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
# The shared SDD work ledger (``WikiProjectConfig.ledger_path``). It always
# resolves to the primary checkout, so a worktree agent filing a finding with
# ``wikitoolkit ledger open`` writes there, never into its own checkout.
SHARED_LEDGER_DIR = Path(".parrot") / "ledger"
# Claude Code keeps every session's scratchpad under this root
# (``/tmp/claude-<uid>/<project-slug>/<session-id>/scratchpad``) and tells the
# seat to use it for temporary files. The sandbox replaces ``/tmp`` with a
# private tmpfs, so the root is bound back in — writable — for all sessions of
# this user at once; every session on the host belongs to the same user.
CLAUDE_SCRATCH_ROOT = Path("/tmp") / f"claude-{os.getuid()}"


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


def shared_ledger_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]:
    """Return the primary checkout's ledger directory when ``root`` is a linked worktree.

    ``wikitoolkit ledger open/claim/close/unclaim`` resolve the ledger through
    ``find_shared_root`` to ``<primary>/.parrot/ledger``. Only that directory
    is returned — SQLite needs its ``-wal``/``-shm`` siblings next to
    ``ledger.db`` — so the wiki plane and the rest of ``.parrot`` stay
    read-only.

    Args:
        root: The checkout root resolved for the command's working directory.
        git_dir: The common Git directory, or ``None`` outside a repository.

    Returns:
        The existing ledger directory to bind writable, or an empty tuple for
        the primary checkout (already writable) and for primaries without a
        ledger.
    """
    if git_dir is None:
        return ()
    primary = git_dir.parent
    if primary == root:
        return ()
    ledger_dir = (primary / SHARED_LEDGER_DIR).resolve()
    if not ledger_dir.is_dir() or ledger_dir.is_relative_to(root):
        return ()
    return (ledger_dir,)


def claude_scratch_root() -> Path:
    """Return Claude Code's per-user scratchpad root, creating it when absent.

    Claude Code creates a session's scratchpad lazily, so the root may not
    exist yet when the first sandboxed command runs. Creating it on the host
    lets a ``mkdir -p`` of the scratchpad from inside the sandbox land on the
    host instead of in the private tmpfs, where it would vanish with the
    command.

    Returns:
        The resolved root directory, private to the current user.
    """
    root = CLAUDE_SCRATCH_ROOT
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root.resolve()


def protected_argv(cwd: Path, argv: Sequence[str]) -> list[str]:
    """Build a fail-closed Linux filesystem sandbox for a command and its children.

    Only the checkout, Git administration directory, the primary checkout's
    worktree directory (``.claude/worktrees``, so a worktree agent can run
    ``git worktree add/remove`` for ``/sdd-done``), the primary checkout's
    shared SDD ledger (``.parrot/ledger``, so a worktree agent can file and
    claim ledger issues), private temporary storage,
    and Claude Code's scratchpad root (``/tmp/claude-<uid>``, bound back over the
    private ``/tmp`` so a seat's scratchpad survives between commands) are
    writable. The rest of the primary checkout and existing shared
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
    # Mounts apply in order: binding after the tmpfs punches the scratchpad
    # root through it while the rest of /tmp stays private.
    scratch_root = claude_scratch_root()
    command.extend(["--bind", str(scratch_root), str(scratch_root)])
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
    for ledger_dir in shared_ledger_dirs(root, git_dir):
        command.extend(["--bind", str(ledger_dir), str(ledger_dir)])
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
    command.extend(["--chdir", str(existing_directory(cwd)), "--", *argv])
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
HOST_MAX_TIMEOUT_MS = 600_000
KILL_GRACE_SECONDS = 5
BACKSTOP_MARGIN_RATIO = 0.25
MIN_BACKSTOP_MARGIN_SECONDS = 5


def _backstop_seconds(seconds: int) -> int:
    """Lift a host-side bound to the sandbox backstop that sits above it.

    Args:
        seconds: The host-side bound in whole seconds.

    Returns:
        That bound plus headroom — ``BACKSTOP_MARGIN_RATIO`` of it, never less
        than ``MIN_BACKSTOP_MARGIN_SECONDS``.
    """
    return seconds + max(MIN_BACKSTOP_MARGIN_SECONDS, math.ceil(seconds * BACKSTOP_MARGIN_RATIO))


def command_timeout_seconds(tool_input: dict[str, Any]) -> int | None:
    """Resolve the wall-clock backstop the sandboxed command must respect.

    A process that prints an error and then never exits — an unclosed
    ``aiosqlite`` worker thread is the classic case — keeps Bubblewrap waiting
    on it, and the host's teardown does not always reach through the sandbox,
    so the command is bounded *inside* the sandbox too.

    That bound is a backstop, never the first kill. The host does not kill a
    foreground Bash call that overruns ``tool_input["timeout"]`` (or its
    default, ``BASH_DEFAULT_TIMEOUT_MS`` / 120 s): it *detaches* it and lets it
    finish in the background. A sandbox kill at exactly the host's bound turns
    that rescue into ``exit 124`` and discards the output of a healthy slow
    command — a merge-tier pytest sweep is the classic case. So every bound
    gets headroom, and an implicit one is lifted to at least the host's maximum
    (``HOST_MAX_TIMEOUT_MS``): once the host has detached a command, nothing
    else will ever reap it.

    Args:
        tool_input: The native ``Bash`` tool input.

    Returns:
        The backstop in whole seconds, or ``None`` for a background command
        without an explicit timeout, which the host never bounds.
    """
    explicit = tool_input.get("timeout")
    if isinstance(explicit, (int, float)) and explicit > 0:
        return _backstop_seconds(max(1, int(explicit // 1000)))
    if tool_input.get("run_in_background"):
        return None
    default_ms = os.environ.get("BASH_DEFAULT_TIMEOUT_MS", "")
    try:
        milliseconds = int(default_ms) if default_ms else HOST_DEFAULT_TIMEOUT_MS
    except ValueError:
        milliseconds = HOST_DEFAULT_TIMEOUT_MS
    return max(_backstop_seconds(max(1, milliseconds // 1000)), HOST_MAX_TIMEOUT_MS // 1000)


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
