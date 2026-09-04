"""Real-subprocess SIGINT / interrupt-before-kill tests (FEAT-521 Module 3/4).

These tests spawn a REAL worker subprocess (`PythonREPLTool` imports
pandas/numpy/matplotlib), so they need a generous `RLIMIT_AS` to boot — see
`real_worker_config` in `test_handle.py`/`test_worker.py`, mirrored here.

Two distinct interrupt mechanisms are covered:
  - Module 3 (`worker.py`): the CHILD side — a raw ``os.kill(pid, SIGINT)``
    delivered directly, independent of any host-side deadline orchestration.
  - Module 4 (`handle.py`): the HOST side — `WorkerHandle.execute()`'s
    two-stage `deadline_ms` -> SIGINT -> `interrupt_grace_ms` -> SIGKILL
    sequence (TASK-2778).
"""

from __future__ import annotations

import asyncio
import importlib
import os
import signal
import sys
import time

import pytest

from parrot.tools.repl_worker.handle import WorkerHandle
from parrot.tools.repl_worker.protocol import WorkerConfig

abstract_module = importlib.import_module("parrot.tools.abstract")

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="SIGINT semantics are POSIX-only")


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    """A per-test report dir that passes `AbstractTool`'s output_dir guard.

    Two halves, both needed: `abstract_module.STATIC_DIR` is patched for
    THIS (parent/test) process — already-imported module constants don't
    see env var changes — while the `STATIC_DIR` env var is set for any
    spawned WORKER subprocess, which re-imports `parrot.conf` fresh and
    inherits the parent's environment (`subprocess.Popen` with no `env=`
    override), so its own `AbstractTool.__init__` guard check passes too.
    """
    monkeypatch.setattr(abstract_module, "STATIC_DIR", tmp_path)
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    return str(tmp_path)


@pytest.fixture
def real_worker_config():
    """Generous AS (spec default ~4 GiB) so the real worker can actually boot."""
    return WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=5, prewarm_pool_size=0)


class TestChildSigint:
    """Module 3: raw SIGINT delivered directly to the worker process."""

    @posix_only
    async def test_worker_interrupt_returns_bounded_result(self, real_worker_config, report_dir):
        """SIGINT mid-`while True: pass` -> bounded ExecResult; worker + namespace survive."""
        handle = WorkerHandle(real_worker_config, output_dir=report_dir)
        await handle.start()
        try:
            await handle.wait_ready()
            exec_task = asyncio.create_task(handle.execute("while True:\n    pass"))
            await asyncio.sleep(0.3)  # let it actually enter the loop
            os.kill(handle._proc.pid, signal.SIGINT)
            result = await exec_task

            assert isinstance(result, dict)
            assert result["status"] == "error"
            assert "interrupted" in result["error"]
            assert handle.is_alive is True
            # `list_ns` (the namespace shadow) still answers post-interrupt.
            names = await handle.list_vars()
            assert isinstance(names, list)
        finally:
            await handle.kill()

    @posix_only
    async def test_worker_sigint_while_idle_is_harmless(self, real_worker_config, report_dir):
        """SIGINT to an idle (not mid-request) worker -> next ping still succeeds."""
        handle = WorkerHandle(real_worker_config, output_dir=report_dir)
        await handle.start()
        try:
            await handle.wait_ready()
            os.kill(handle._proc.pid, signal.SIGINT)
            await asyncio.sleep(0.3)  # let the worker's service loop absorb it
            assert await handle.ping() is True
            assert handle.is_alive is True
        finally:
            await handle.kill()


class TestTwoStageDeadline:
    """Module 4: `WorkerHandle.execute()`'s deadline -> SIGINT -> SIGKILL sequence."""

    @posix_only
    async def test_execute_deadline_interrupts_first(self, report_dir):
        """AC3: a runaway pure-Python loop is interrupted, not killed — namespace intact."""
        config = WorkerConfig(
            deadline_ms=1_000,
            interrupt_grace_ms=600,
            interrupt_before_kill=True,
            max_workers=2,
            idle_ttl_seconds=5,
            prewarm_pool_size=0,
        )
        handle = WorkerHandle(config, output_dir=report_dir)
        await handle.start()
        try:
            await handle.wait_ready()
            await handle.execute("x = 42")

            started = time.monotonic()
            result = await handle.execute("while True:\n    pass")
            elapsed = time.monotonic() - started

            assert isinstance(result, dict)
            assert result["status"] == "error"
            assert "interrupted" in result["error"]
            assert "ALL variables" not in result["error"]  # never a namespace-loss error
            assert handle.is_alive is True
            # Bounded by deadline_ms + interrupt_grace_ms + grace (spec G6),
            # generous CI tolerance while still asserting the absolute bound.
            assert elapsed < (config.deadline_ms + config.interrupt_grace_ms + 1_500) / 1000

            # Previously bound variable still readable — namespace preserved.
            assert await handle.get_var("x") == 42
        finally:
            await handle.kill()

    @posix_only
    async def test_execute_falls_back_to_sigkill(self, report_dir):
        """AC4: a SIGINT-resistant snippet is SIGKILLed within the configured bound.

        `sum(range(N))` for a large N iterates entirely in C — CPython only
        checks for a pending signal between INTERPRETED bytecode
        instructions, so a snippet that never returns to the interpreter
        loop cannot observe the interrupt until it finishes (or is killed).
        `import signal` itself is denylisted by the security gate, so this
        is the security-gate-legal way to reproduce SIGINT-resistant code
        (the alternative the spec's own test-spec comment suggests,
        `signal.pthread_sigmask`, is not reachable from sandboxed code).
        """
        config = WorkerConfig(
            deadline_ms=1_000,
            interrupt_grace_ms=500,
            interrupt_before_kill=True,
            max_workers=2,
            idle_ttl_seconds=5,
            prewarm_pool_size=0,
        )
        handle = WorkerHandle(config, output_dir=report_dir)
        await handle.start()
        try:
            await handle.wait_ready()
            started = time.monotonic()
            result = await handle.execute("sum(range(10**11))")
            elapsed = time.monotonic() - started

            assert isinstance(result, dict)
            assert result["status"] == "error"
            assert "timeout" in result["result"].lower()
            assert handle.is_alive is False
            # Bound: deadline_ms + interrupt_grace_ms + _DEADLINE_GRACE_MS(250ms).
            budget_s = (config.deadline_ms + config.interrupt_grace_ms + 250) / 1000
            assert elapsed < budget_s + 1.0, "generous CI tolerance on top of the absolute bound"
        finally:
            await handle.kill()

    @posix_only
    async def test_loss_error_names_verdict(self, report_dir):
        """AC (spec G2/G3): the timeout loss error names the observer's verdict + last sample."""
        config = WorkerConfig(
            deadline_ms=1_000,
            interrupt_grace_ms=500,
            interrupt_before_kill=True,
            max_workers=2,
            idle_ttl_seconds=5,
            prewarm_pool_size=0,
        )
        handle = WorkerHandle(config, output_dir=report_dir)
        await handle.start()
        try:
            await handle.wait_ready()
            result = await handle.execute("sum(range(10**11))")

            assert isinstance(result, dict)
            assert "timeout" in result["error"].lower()
            assert "verdict=" in result["error"]
            assert any(word in result["error"] for word in ("computing", "stalled", "settled"))
            assert "cpu=" in result["error"] and "rss=" in result["error"]
        finally:
            await handle.kill()

    async def test_interrupt_before_kill_false_preserves_immediate_kill(self, report_dir):
        """`interrupt_before_kill=False` keeps the pre-FEAT-521 deterministic-kill behavior."""
        config = WorkerConfig(
            deadline_ms=1_000,
            interrupt_grace_ms=500,  # unused when interrupt_before_kill=False, but still validated
            interrupt_before_kill=False,
            max_workers=2,
            idle_ttl_seconds=5,
            prewarm_pool_size=0,
        )
        handle = WorkerHandle(config, output_dir=report_dir)
        await handle.start()
        try:
            await handle.wait_ready()
            started = time.monotonic()
            result = await handle.execute("while True:\n    pass")
            elapsed = time.monotonic() - started

            assert isinstance(result, dict)
            assert result["status"] == "error"
            assert "timeout" in result["result"].lower()
            assert "interrupted" not in result["result"]
            assert handle.is_alive is False
            # No interrupt_grace_ms wait — killed at (roughly) deadline_ms alone.
            assert elapsed < (config.deadline_ms + 1_500) / 1000
        finally:
            await handle.kill()
