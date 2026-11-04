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
import subprocess
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
    worktree that is the primary checkout's worktree root, so the next
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


# The shared SDD work ledger (``WikiProjectConfig.ledger_path``). It always
# resolves to the primary checkout, so a worktree agent filing a finding with
# ``wikitoolkit ledger open`` writes there, never into its own checkout.
SHARED_LEDGER_DIR = Path(".parrot") / "ledger"
# Claude Code keeps every session's scratchpad under this root
# (``/tmp/claude-<uid>/<project-slug>/<session-id>/scratchpad``) and tells the
# seat to use it for temporary files. The sandbox replaces ``/tmp`` with a
# private tmpfs, so the root is bound back in — writable — for all sessions of
# this user at once; every session on the host belongs to the same user.
# ``os.getuid`` does not exist on Windows; the hook must still import there.
# The path is only used by the POSIX sandbox.
CLAUDE_SCRATCH_ROOT = Path("/tmp") / f"claude-{os.getuid() if hasattr(os, 'getuid') else 0}"


def worktree_admin_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]:
    """Return the primary checkout's worktree directory when ``root`` is a linked worktree.

    Linked worktrees (feature and pool checkouts) live under the primary
    checkout's resolved worktree root (default ``.parrot/worktrees``). ``/sdd-done`` run from inside one must
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
    from parrot.sdd.config import worktree_root  # lazy: the hook path stays stdlib-only until needed

    admin_dir = worktree_root(primary).resolve()
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


def protected_argv(cwd: Path, argv: Sequence[str], *, derive_pythonpath: bool = False) -> list[str]:
    """Build a fail-closed Linux filesystem sandbox for a command and its children.

    Only the checkout, Git administration directory, the primary checkout's
    worktree directory (the resolved worktree root, so a worktree agent can run
    ``git worktree add/remove`` for ``/sdd-done``), the primary checkout's
    shared SDD ledger (``.parrot/ledger``, so a worktree agent can file and
    claim ledger issues), private temporary storage,
    and Claude Code's scratchpad root (``/tmp/claude-<uid>``, bound back over the
    private ``/tmp`` so a seat's scratchpad survives between commands) are
    writable. The rest of the primary checkout and existing shared
    environments remain read-only even when the checkout is the primary
    repository. No host chmod or mount changes are performed. Network
    isolation is outside this policy's scope.

    ``derive_pythonpath=True`` omits the ``--setenv PYTHONPATH`` literal: the caller sets ``PYTHONPATH`` in the
    command's environment (see ``derived_pythonpath_assignment``), which ``bwrap`` passes through.
    """
    if not argv:
        raise ValueError("A command is required.")
    executable = shutil.which("bwrap")
    if executable is None:
        raise RuntimeError(
            "Bubblewrap (bwrap) is required for the legacy SDD hook and is not available on "
            f"{sys.platform}; refusing unsandboxed execution. Launch the worker with "
            "`parrot sdd launch worker <FEAT-ID>` (native sandbox) instead."
        )
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
    if source_roots and not derive_pythonpath:
        python_path = os.pathsep.join(map(str, source_roots))
        if inherited := os.environ.get("PYTHONPATH"):
            python_path += os.pathsep + inherited
        command.extend(["--setenv", "PYTHONPATH", python_path])
    command.extend(["--chdir", str(existing_directory(cwd)), "--", *argv])
    return command


def derived_pythonpath_assignment(root: Path) -> str:
    """Shell text assigning ``PYTHONPATH`` from ``<root>/packages/*/src`` when the command runs.

    Listing every package ``src`` is a ~3 KB literal that a model must echo back verbatim after an auto-mode
    refusal; the glob keeps the rewrite short and yields the same value. A pre-existing ``PYTHONPATH`` is appended.

    Args:
        root: The checkout root whose ``packages/*/src`` directories form the path.

    Returns:
        A ``PYTHONPATH="…"`` assignment, safe as an ``env`` argument or a command prefix.
    """
    packages = shlex.quote(str(root / "packages"))
    return f"PYTHONPATH=\"$(printf '%s:' {packages}/*/src | sed 's/:$//')${{PYTHONPATH:+:$PYTHONPATH}}\""


_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "flows" / "dev_loop"


def _load_guard_bash() -> Any:
    """Import the stdlib-only test-scope guard without importing Parrot.

    Returns:
        The kernel's ``guard_bash`` callable.

    Raises:
        ImportError: The checkout serving this hook has no test-scope kernel.
    """
    if str(_KERNEL_PARENT) not in sys.path:
        sys.path.insert(0, str(_KERNEL_PARENT))
    from test_scope.guard import guard_bash

    return guard_bash


_COMPOUND_MARKERS = ("&&", "||", ";", "|")


_RUNNER_HEADS = frozenset({"pytest", "python", "python3", "vitest", "pnpm", "npx", "cargo", "uv"})


def _is_lone_runner_command(command: str) -> bool:
    """True for a single runner invocation (pytest, vitest, pnpm/npx, cargo, uv) with no shell compounding.

    Args:
        command: The Bash command the seat issued.

    Returns:
        Whether it is one runner command; compounds are never lone (brainstorm Q6).
    """
    stripped = command.strip()
    if any(marker in stripped for marker in _COMPOUND_MARKERS):
        return False
    try:
        argv = shlex.split(stripped)
    except ValueError:
        return False
    return bool(argv) and Path(argv[0]).name in _RUNNER_HEADS


def _scope_guard(command: str, cwd: Path) -> tuple[str, str | None]:
    """Decide whether a native Bash command runs an over-broad pytest (FEAT-563).

    Args:
        command: The Bash command the seat issued.
        cwd: The hook's working directory.

    Returns:
        ``("allow", None)``, ``("rewrite"|"verdict", <command>)`` or ``("block", <message>)``.
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
    if outcome.action in ("rewrite", "verdict") and rewritten:
        # The kernel's verdict command already begins with `cd <root> &&`; a plain
        # rewrite is root-relative, so a lone runner invocation issued from a different
        # directory needs an explicit `cd` first (spec R2). A command that already
        # mixes its own `cd`/segments keeps its author's cwd handling.
        if outcome.action == "rewrite" and root != cwd and _is_lone_runner_command(command):
            rewritten = f"cd {shlex.quote(str(root))} && {rewritten}"
        return outcome.action, rewritten
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


# RTK compacts command output through its own global ``PreToolUse`` hook. When
# both hooks rewrite a Bash call, the host keeps only one ``updatedInput`` and
# does not define which: usually this module's wrapper of the *original*
# command, so RTK's rewrite is lost, but sometimes RTK's, which then runs
# unsandboxed. The RTK rewrite is applied here, inside the sandbox; keeping the
# global hook out of sandboxed sessions is the caller's job.
#
# RTK's data directory stays read-only in the sandbox on purpose. It holds
# ``trusted_filters.json``, the trust store for project-local
# ``.rtk/filters.toml``; a seat that could write it could trust its own filter
# and change what RTK shows outside the sandbox. RTK skips its tracking and
# ``tee`` writes when they fail, so sandboxed runs only go uncounted by
# ``rtk gain``.
RTK_ENV_SWITCH = "PARROT_SANDBOX_RTK"
RTK_REWRITE_TIMEOUT_SECONDS = 5


def rtk_rewrite(command: str) -> str | None:
    """Return RTK's token-optimized form of ``command``, or ``None`` to keep it as is.

    ``rtk rewrite`` prints the rewritten command when RTK has an equivalent and
    prints nothing when it has none. Only that output is trusted, because the
    exit status is RTK's permission verdict against the Claude settings: 0 when
    an allow rule matches, 3 when the host should ask, 2 (with no output) when a
    deny rule matches. This hook grants no approval, so 0 and 3 are equivalent
    here. ``--`` ends RTK's own options, so a command that starts with ``-`` is
    rewritten as text instead of being parsed as an RTK flag. Every failure
    (RTK not installed, disabled with ``PARROT_SANDBOX_RTK=0``, a timeout, a
    crash) keeps the original command, because output compaction must never
    block a command.

    Args:
        command: The shell text to run, after the test-scope guard.

    Returns:
        The rewritten command, or ``None`` when RTK is unavailable or has no equivalent.
    """
    if os.environ.get(RTK_ENV_SWITCH, "1") == "0":
        return None
    executable = shutil.which("rtk")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "rewrite", "--", command],
            capture_output=True,
            text=True,
            timeout=RTK_REWRITE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    rewritten = result.stdout.rstrip("\n")
    return rewritten if rewritten.strip() else None


def _load_native_sandbox() -> Any:
    """Return the sibling ``native_claude_sandbox`` module (FEAT-768; moved next door by TASK-5093).

    Imported lazily so the Bubblewrap backend never pays for it. The sibling imports this module back
    (``import worktree_environment`` in script mode), so the running module is pre-seeded under that name
    to keep one copy of the policy helpers.
    """
    if __package__:
        from . import native_claude_sandbox
    else:  # run as a script: this file's directory is sys.path[0]
        sys.modules.setdefault("worktree_environment", sys.modules[__name__])
        import native_claude_sandbox
    return native_claude_sandbox


DEGRADED_BANNER = "echo '[sdd] degraded sandbox: no OS write boundary' >&2; "

#: Hook backends. ``auto`` (the ``main()`` default) picks native or Bubblewrap when the command runs;
#: ``bubblewrap`` is the explicit legacy wrapper; ``claude-native`` is the launcher's fail-closed mode.
BACKENDS = ("auto", "bubblewrap", "claude-native")
# Exported together with `claude-native` by `native_claude_sandbox.launch_worker` and the dev-loop dispatcher.
LAUNCHER_MARKERS = ("PARROT_SDD_SANDBOX_ROOTS", "PARROT_SDD_CACHE_DIR")
#: Linux user-namespace map; a single-uid map that is not the identity map means a sandboxed command.
UID_MAP_PATH = "/proc/self/uid_map"
NATIVE_BWRAP_DENIAL = "native sandbox is active; resend the command without the bwrap wrapper"
_ELSE = " ; else "
_FI = " ; fi"


def _native_check() -> str:
    """Shell test that is true only inside Claude Code's native sandbox.

    ``SANDBOX_RUNTIME=1`` and, where ``uid_map`` exists (Linux), a single line that is not the identity
    map (``0 0 …``). macOS (Seatbelt) has no ``uid_map`` and relies on ``SANDBOX_RUNTIME`` alone; that
    platform is not certified.
    """
    path = shlex.quote(UID_MAP_PATH)
    return (
        '[ "${SANDBOX_RUNTIME:-}" = 1 ] && '
        f"{{ [ ! -r {path} ] || {{ [ \"$(grep -c '' {path})\" = 1 ] && ! grep -Eq '^ *0 +0 ' {path}; }}; }}"
    )


def _branch(then: str, otherwise: str) -> str:
    """Compose the one-shot ``if`` wrapper: the native check selects exactly one of two commands."""
    return f"if {_native_check()}; then {then}{_ELSE}{otherwise}{_FI}"


def _wrap_bash(command: str, cwd: Path, tool_input: dict[str, Any], native: Any, backend: str = "") -> str:
    """Run one Bash command through the scope guard, RTK and the sandbox wrapper.

    Args:
        command: The shell text to wrap.
        cwd: The hook's working directory.
        tool_input: The native ``Bash`` tool input, for the timeout fields.
        native: The ``native_claude_sandbox`` module, or ``None`` for Bubblewrap.
        backend: ``auto`` (runtime branch: native inside the native sandbox, ``bwrap`` outside),
            ``claude-native`` (the launcher's session: trusted, env diff only, no rewrite when nothing
            changes) or ``bubblewrap``. Empty derives it from ``native``.

    Returns:
        The wrapped command line.

    Raises:
        ValueError: The test-scope guard blocked the command.
    """
    backend = backend or ("claude-native" if native else "bubblewrap")
    task_cwd = native.native_task_cwd(cwd, command) if native else cwd
    action, value = _scope_guard(command, task_cwd)
    if action == "block":
        raise ValueError(value or "over-broad pytest blocked by the test-scope guard")
    if action in ("rewrite", "verdict") and value:
        command = value
    # After the guard, which must see the raw runner (`pytest`, not `rtk pytest`).
    if optimized := rtk_rewrite(command):
        command = optimized
    degraded = bool(native) and os.environ.get(native.DEGRADED_ENV) == "1"
    if degraded:
        command = DEGRADED_BANNER + command
    if native and backend == "claude-native":
        # The launcher started this session inside the native sandbox and exported the session-fixed
        # variables, so emit only what differs, and bound the call only when the host would not already
        # (an explicit `timeout` or `run_in_background`; a plain call is bounded by the host itself).
        # A plain command with nothing to change is returned as is: no rewrite, no auto-mode refusal.
        env = native.native_command_environment(task_cwd)
        diff = {key: value for key, value in env.items() if os.environ.get(key) != value}
        explicit = bool(tool_input.get("timeout") or tool_input.get("run_in_background"))
        if not diff and not explicit:
            return command
        shell = bounded_shell_argv(command, tool_input) if explicit else ["/bin/bash", "-c", command]
        return shlex.join(["env", *(f"{key}={value}" for key, value in diff.items()), *shell])
    shell = bounded_shell_argv(command, tool_input)
    if native:  # auto: the launcher did not run, so the full environment is needed in the native branch
        env = native.native_command_environment(task_cwd)
        assignments = []
        for key, value in env.items():
            if key == "PYTHONPATH":
                assignments.append(derived_pythonpath_assignment(native._native_roots(task_cwd)[0]))
            else:
                assignments.append(shlex.quote(f"{key}={value}"))
        wrapped = f"env {' '.join(assignments)} {shlex.join(shell)}"
        # Guard, RTK and the bounded shell ran once above; only the sandbox wrapper differs per branch.
        root = repository_paths(cwd)[0]
        if (root / "packages").is_dir() and any((root / "packages").glob("*/src")):
            outside = f"{derived_pythonpath_assignment(root)} {shlex.join(protected_argv(cwd, shell, derive_pythonpath=True))}"
        else:
            outside = shlex.join(protected_argv(cwd, shell))
        return _branch(wrapped, outside)
    return shlex.join(protected_argv(cwd, shell))


def _wrap_auto(command: str, cwd: Path, tool_input: dict[str, Any]) -> str:
    """Wrap ``command`` for the ``auto`` backend: one native branch and one ``bwrap`` branch.

    The shell picks the branch at run time, so nothing ever runs unsandboxed and no ``bwrap`` is
    nested inside the native sandbox.
    """
    return _wrap_bash(command, cwd, tool_input, _load_native_sandbox(), "auto")


def _is_own_wrapper(command: str, cwd: Path, tool_input: dict[str, Any], native: Any, backend: str = "") -> bool:
    """True when ``command`` is exactly what this hook would emit for the command it wraps.

    Auto mode reviews a Bash call before hooks run; when a hook changes it, the
    agent must resend the rewritten text verbatim. Re-wrapping that text would
    change it again on every attempt, so auto mode could never approve it. The
    inner command is run through the full pipeline again — guard, RTK, wrapper —
    and only a byte-identical result counts, so a hand-written look-alike wrapper
    never skips the guard. Handles the three backends: the ``bubblewrap`` and ``claude-native``
    shapes end in ``/bin/bash -c <inner>``; the ``auto`` shape is an ``if`` wrapper whose first
    branch does. An unchanged ``claude-native`` command is its own fixed point.

    Args:
        command: The Bash command the seat issued.
        cwd: The hook's working directory.
        tool_input: The native ``Bash`` tool input.
        native: The ``native_claude_sandbox`` module, or ``None`` for Bubblewrap/auto.
        backend: ``auto``, ``bubblewrap`` or ``claude-native``; empty derives it from ``native``.

    Returns:
        Whether the command is already this hook's own, unchanged output.
    """
    backend = backend or ("claude-native" if native else "bubblewrap")
    candidates = [command]
    head = f"if {_native_check()}; then "
    if command.startswith(head) and command.endswith(_FI):
        body = command[len(head) : -len(_FI)]
        # The inner command may itself contain the separator: try every split, the rebuild decides.
        candidates = [body[:i] for i in range(len(body)) if body.startswith(_ELSE, i)]
    for candidate in candidates:
        try:
            argv = shlex.split(candidate)
        except ValueError:
            continue
        if len(argv) < 4 or argv[-3:-1] != ["/bin/bash", "-c"]:
            continue
        inner = argv[-1]
        if native and os.environ.get(native.DEGRADED_ENV) == "1":
            inner = inner.removeprefix(DEGRADED_BANNER)
        try:
            if backend == "auto":
                rebuilt = _wrap_auto(inner, cwd, tool_input)
            else:
                rebuilt = _wrap_bash(inner, cwd, tool_input, native, backend)
        except (OSError, ValueError, RuntimeError, KeyError):
            continue
        if rebuilt == command:
            return True
    return False


def _is_handwritten_bwrap(command: str) -> bool:
    """True when the first word of ``command`` is ``bwrap`` or a path ending in ``/bwrap``."""
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    return bool(words) and (words[0] == "bwrap" or words[0].endswith("/bwrap"))


def hook_response(payload: dict[str, Any], *, backend: str = "bubblewrap") -> dict[str, Any]:
    """Apply guards and file checks for one of three backends; deny invalid modes.

    * ``bubblewrap`` (the keyword default; explicit legacy): always wrap in ``bwrap``.
    * ``claude-native`` (launcher): never nest ``bwrap``. The launcher's backend variable is trusted (the
      hook cannot see the sandbox), so there is no runtime check; the command is rewritten only when its
      environment differs from the inherited one, the guard/RTK changed it, or it carries an explicit
      ``timeout``/``run_in_background``. A hand-written ``bwrap`` command is denied.
    * ``auto`` (what ``main()`` selects when the backend is unset): one wrapper that runs natively
      inside the native sandbox and through ``bwrap`` outside it.

    The Bash rewrite is idempotent: a command that already is this hook's output
    passes through without ``updatedInput``, so auto mode can review the resent call.
    """
    cwd = Path(payload["cwd"])
    tool_input = payload["tool_input"]
    output: dict[str, Any] = {"hookEventName": "PreToolUse"}
    try:
        if backend not in BACKENDS:
            raise ValueError(f"Unknown SDD sandbox backend {backend!r}; refusing to run")
        native = _load_native_sandbox() if backend == "claude-native" else None
        if payload["tool_name"] == "Bash":
            command = tool_input["command"]
            if not isinstance(command, str) or not command:
                raise ValueError("Bash command must be a non-empty string")
            if backend == "claude-native" and _is_handwritten_bwrap(command):
                raise ValueError(NATIVE_BWRAP_DENIAL)
            if not _is_own_wrapper(command, cwd, tool_input, native, backend):
                # Preserve timeout/background/description without granting approval
                # or overriding decisions from other hooks.
                wrapped = (
                    _wrap_auto(command, cwd, tool_input)
                    if backend == "auto"
                    else _wrap_bash(command, cwd, tool_input, native, backend)
                )
                if wrapped != command:  # a native no-op needs no rewrite, so auto mode never refuses it
                    output["updatedInput"] = {**tool_input, "command": wrapped}
        else:
            path = tool_input.get("file_path") or tool_input.get("notebook_path")
            if not isinstance(path, str):
                raise ValueError("File tool requires a path")
            if native:
                native.validate_native_write_path(cwd, cwd / path)
            else:
                validate_write_path(cwd, cwd / path)
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        output.update(permissionDecision="deny", permissionDecisionReason=str(exc))
    return {"hookSpecificOutput": output}


def main(argv: Sequence[str] | None = None) -> None:
    """Serve a native PreToolUse hook without importing application dependencies."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hook", action="store_true", required=True)
    parser.parse_args(argv)
    try:
        backend = os.environ.get("PARROT_SDD_SANDBOX_BACKEND")
        native_markers = ("PARROT_SDD_CACHE_DIR", "PARROT_SDD_SANDBOX_ROOTS", "PARROT_SDD_SANDBOX_DEGRADED")
        if not backend and any(os.environ.get(name) for name in native_markers):
            # A native launch always sets the backend; its absence next to the launcher's other markers
            # means a broken launch, not an unlaunched session — refuse rather than guess.
            raise RuntimeError(
                "native launch markers present but PARROT_SDD_SANDBOX_BACKEND is unset; refusing to guess a wrapper"
            )
        if backend == "claude-native" and not all(os.environ.get(name) for name in LAUNCHER_MARKERS):
            # `claude-native` skips the runtime check, so it is trusted only beside the markers the
            # launcher and the dev-loop dispatcher always export with it. A hand-exported value without
            # them gets `auto`: native inside the native sandbox, Bubblewrap outside, never unsandboxed.
            backend = "auto"
        # Unset selects `auto`: native inside the native sandbox, Bubblewrap outside. The legacy wrapper
        # is an explicit opt-in (`PARROT_SDD_SANDBOX_BACKEND=bubblewrap`).
        result = hook_response(json.load(sys.stdin), backend=backend or "auto")
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
