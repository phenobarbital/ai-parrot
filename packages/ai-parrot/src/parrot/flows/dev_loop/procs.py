"""Bounded subprocess execution for the dev-loop kernels.

Every subprocess the `sdd_coder` engine spawns from an MCP request handler
(`git`, `ruff`, `black`) used to be awaited with a bare ``proc.communicate()``:
no deadline, stdin inherited from the server (the JSON-RPC channel itself),
and git free to open an editor or a credential prompt. A single hung child
therefore pinned the handler forever, and because the stdio MCP server
processed requests one at a time, every later call — read-only ones
included — died at the MCP host's 30-minute idle timeout.

`run_bounded` is the one place that spawns those children now: own process
group, ``stdin=DEVNULL``, a wall-clock deadline that kills the whole owned
tree, and a conventional ``124`` return code on expiry so callers keep their
existing ``rc != 0`` error paths.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from typing import Dict, Mapping, Optional, Sequence, Tuple

#: Default wall-clock cap for one engine-owned child process, in seconds.
DEFAULT_SUBPROCESS_TIMEOUT_S: float = 300.0

#: Return code reported when the deadline expires (coreutils ``timeout`` convention).
TIMEOUT_RC: int = 124

#: Return code reported when the executable cannot be spawned at all.
SPAWN_FAILED_RC: int = 127

_TERMINATE_GRACE_S: float = 2.0


def git_env(base: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Environment for a headless, never-prompting ``git`` child.

    Args:
        base: Environment to start from; defaults to ``os.environ``.

    Returns:
        A copy of *base* with every interactive git surface disabled: no
        terminal credential prompt, no editor (``true`` accepts the default
        message), no pager, and no optional index-refresh locks so a
        concurrent session cannot make a read-only command fail or wait.
    """
    env = dict(os.environ if base is None else base)
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_EDITOR": "true",
            "GIT_SEQUENCE_EDITOR": "true",
            "GIT_PAGER": "cat",
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    return env


async def _kill_tree(proc: "asyncio.subprocess.Process") -> None:
    """SIGTERM then SIGKILL the child's whole process group; never raises."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if proc.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(proc.pid, sig)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=_TERMINATE_GRACE_S)


async def run_bounded(
    argv: Sequence[str],
    *,
    cwd: Optional[str] = None,
    timeout_s: float = DEFAULT_SUBPROCESS_TIMEOUT_S,
    env: Optional[Mapping[str, str]] = None,
) -> Tuple[int, str, str]:
    """Run *argv* with a wall-clock deadline and return ``(rc, stdout, stderr)``.

    The child gets its own session (so it can neither read the server's stdin
    nor reach a controlling terminal) and ``stdin=DEVNULL``. When *timeout_s*
    elapses the whole process group is terminated and ``(124, "", <reason>)``
    is returned; when the executable cannot be spawned ``(127, "", <reason>)``
    is returned. Cancellation of the awaiting task also kills the child before
    propagating.

    Args:
        argv: Program and arguments.
        cwd: Working directory for the child.
        timeout_s: Wall-clock cap in seconds.
        env: Environment for the child; inherits the server's when ``None``.

    Returns:
        ``(returncode, stdout, stderr)`` with both streams decoded as UTF-8
        (undecodable bytes replaced).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=None if env is None else dict(env),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except (FileNotFoundError, OSError) as exc:
        # asyncio's FileNotFoundError carries no filename; name the executable ourselves.
        return SPAWN_FAILED_RC, "", f"{argv[0]}: {exc}"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        await _kill_tree(proc)
        return TIMEOUT_RC, "", f"{argv[0]} timed out after {timeout_s:g}s: {' '.join(argv)}"
    except asyncio.CancelledError:
        await _kill_tree(proc)
        raise
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
