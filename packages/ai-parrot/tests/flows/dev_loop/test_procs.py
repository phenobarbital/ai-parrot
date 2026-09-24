"""Tests for `parrot.flows.dev_loop.procs` — bounded, headless subprocess execution."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time

import pytest

from parrot.flows.dev_loop.procs import SPAWN_FAILED_RC, TIMEOUT_RC, git_env, run_bounded

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")


@pytest.mark.asyncio
async def test_run_bounded_returns_streams_and_rc() -> None:
    rc, out, err = await run_bounded(
        [sys.executable, "-c", "import sys; print('hi'); print('warn', file=sys.stderr); sys.exit(3)"],
        timeout_s=30,
    )
    assert rc == 3
    assert out.strip() == "hi"
    assert err.strip() == "warn"


@pytest.mark.asyncio
async def test_run_bounded_kills_the_child_tree_on_timeout() -> None:
    # The child spawns a grandchild and reports its pid, then both sleep. On expiry the
    # whole process group must be gone — a plain `proc.kill()` would leave the grandchild.
    script = (
        "import os, subprocess, sys, time\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print(p.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    # We cannot read stdout before expiry through run_bounded (it returns "" on timeout),
    # so route the pid through a file instead.
    import tempfile

    with tempfile.NamedTemporaryFile("w+", delete=False) as fh:
        pid_file = fh.name
    script = script.replace("print(p.pid, flush=True)", f"open({pid_file!r}, 'w').write(str(p.pid))")

    t0 = time.monotonic()
    rc, out, err = await run_bounded([sys.executable, "-c", script], timeout_s=0.5)
    elapsed = time.monotonic() - t0

    assert rc == TIMEOUT_RC
    assert out == ""
    assert "timed out after 0.5s" in err
    assert elapsed < 10, "expiry must not wait for the child's own sleep"

    with open(pid_file) as fh:
        grandchild = int(fh.read().strip())
    os.unlink(pid_file)
    # Give the kernel a moment to reap, then the grandchild must be gone.
    for _ in range(50):
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.05)
    else:
        os.kill(grandchild, signal.SIGKILL)
        pytest.fail("grandchild survived the bounded kill")


@pytest.mark.asyncio
async def test_run_bounded_reports_spawn_failure_instead_of_raising() -> None:
    rc, out, err = await run_bounded(["/definitely/not/a/binary"], timeout_s=5)
    assert rc == SPAWN_FAILED_RC
    assert out == ""
    assert "not/a/binary" in err


@pytest.mark.asyncio
async def test_run_bounded_child_cannot_read_our_stdin() -> None:
    # stdin is DEVNULL: a child that tries to read gets EOF immediately instead of
    # consuming the MCP server's JSON-RPC channel (or blocking on it).
    rc, out, _err = await run_bounded([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"], timeout_s=10)
    assert rc == 0
    assert out.strip() == "''"


@pytest.mark.asyncio
async def test_run_bounded_kills_child_on_cancellation() -> None:
    task = asyncio.create_task(run_bounded([sys.executable, "-c", "import time; time.sleep(60)"], timeout_s=60))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_git_env_disables_every_interactive_surface() -> None:
    env = git_env({"PATH": "/usr/bin", "GIT_EDITOR": "vim"})
    assert env["PATH"] == "/usr/bin"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_EDITOR"] == "true"
    assert env["GIT_SEQUENCE_EDITOR"] == "true"
    assert env["GIT_PAGER"] == "cat"
    assert env["GIT_OPTIONAL_LOCKS"] == "0"


@pytest.mark.asyncio
async def test_git_env_reaches_the_child() -> None:
    rc, out, _err = await run_bounded(
        [sys.executable, "-c", "import os; print(os.environ['GIT_TERMINAL_PROMPT'], os.environ['GIT_EDITOR'])"],
        timeout_s=10,
        env=git_env(),
    )
    assert rc == 0
    assert out.split() == ["0", "true"]
