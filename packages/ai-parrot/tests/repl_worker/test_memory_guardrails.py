"""Real-subprocess soft/hard RSS guardrail tests (FEAT-521 Module 4/6).

These tests spawn REAL worker subprocesses (`PythonREPLTool` imports
pandas/numpy/matplotlib), so they need a generous default `RLIMIT_AS` (spec
default ~4 GiB) to boot, and allocate real memory to cross the configured
soft/hard RSS thresholds deterministically.
"""

from __future__ import annotations

import asyncio
import importlib
import time

import psutil
import pytest

from parrot.tools.pythonrepl import PythonREPLTool
from parrot.tools.repl_worker.handle import WorkerHandle
from parrot.tools.repl_worker.protocol import WorkerConfig

abstract_module = importlib.import_module("parrot.tools.abstract")


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    """A per-test report dir that passes `AbstractTool`'s output_dir guard.

    Both halves are needed: `abstract_module.STATIC_DIR` is patched for THIS
    (parent/test) process, and the `STATIC_DIR` env var is set for any
    spawned WORKER subprocess (which re-imports `parrot.conf` fresh and
    inherits the parent's environment) — see `test_interrupt.py`'s
    `report_dir` fixture docstring for the full finding.
    """
    monkeypatch.setattr(abstract_module, "STATIC_DIR", tmp_path)
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    return str(tmp_path)


async def _shutdown(tool: PythonREPLTool) -> None:
    if tool._worker_pool is not None:
        await tool._worker_pool.shutdown()


class TestHardLimit:
    async def test_memory_hard_kill_is_deterministic(self, report_dir):
        """AC6: crossing `memory_hard_limit_bytes` kills within ~one poll
        interval, cause `memory` with measured RSS — no stderr dependence."""
        config = WorkerConfig(
            deadline_ms=20_000,
            observer_poll_ms=100,
            memory_soft_limit_bytes=0,
            memory_hard_limit_bytes=300 * 1024 * 1024,
        )
        handle = WorkerHandle(config, output_dir=report_dir)
        await handle.start()
        try:
            await handle.wait_ready()
            started = time.monotonic()
            result = await handle.execute("x = bytearray(350 * 1024 * 1024)")
            elapsed = time.monotonic() - started

            assert isinstance(result, dict)
            assert result["status"] == "error"
            assert "memory" in result["error"]
            assert "verdict=" in result["error"]  # observer.describe() folded in
            assert handle.is_alive is False
            assert elapsed < 5.0, "generous bound: allocation + a couple poll intervals"
        finally:
            await handle.kill()


class TestSoftLimit:
    async def test_soft_hint_appended_to_string_result(self, report_dir):
        """AC7: exactly one hint line on the next STRING result, none before."""
        config = WorkerConfig(
            deadline_ms=20_000,
            observer_poll_ms=100,
            memory_soft_limit_bytes=320 * 1024 * 1024,
            memory_hard_limit_bytes=0,
        )
        handle = WorkerHandle(config, output_dir=report_dir)
        await handle.start()
        try:
            await handle.wait_ready()
            before = await handle.execute("1+1")
            assert isinstance(before, str)
            assert "[REPL memory]" not in before

            await handle.execute("x = bytearray(150 * 1024 * 1024)")
            await asyncio.sleep(0.3)  # let the observer sample
            after = await handle.execute("2+2")
            assert isinstance(after, str)
            assert "[REPL memory]" in after
            assert after.count("[REPL memory]") == 1
        finally:
            await handle.kill()

    async def test_soft_hint_appended_to_dict_result(self, report_dir):
        """AC7: the same hint on the `result` field of an error dict."""
        config = WorkerConfig(
            deadline_ms=20_000,
            observer_poll_ms=100,
            memory_soft_limit_bytes=320 * 1024 * 1024,
            memory_hard_limit_bytes=0,
        )
        handle = WorkerHandle(config, output_dir=report_dir)
        await handle.start()
        try:
            await handle.wait_ready()
            await handle.execute("x = bytearray(150 * 1024 * 1024)")
            await asyncio.sleep(0.3)
            result = await handle.execute("1/0")
            assert isinstance(result, dict)
            assert "ZeroDivisionError" in result["result"]
            # The hint is appended to `result` specifically (spec §2: "the
            # next execute() result ... gets a trailing line") — `error`
            # stays the plain worker-reported message, unsuffixed.
            assert "[REPL memory]" in result["result"]
            assert "[REPL memory]" not in result["error"]
            assert result["result"].startswith(result["error"])
        finally:
            await handle.kill()

    async def test_soft_hint_clears_after_90_percent_rearm(self, report_dir):
        """AC7: hysteresis — the hint disappears once RSS drops below 90% of soft."""
        config = WorkerConfig(
            deadline_ms=20_000,
            observer_poll_ms=100,
            memory_soft_limit_bytes=320 * 1024 * 1024,
            memory_hard_limit_bytes=0,
        )
        handle = WorkerHandle(config, output_dir=report_dir)
        await handle.start()
        try:
            await handle.wait_ready()
            await handle.execute("x = bytearray(150 * 1024 * 1024)")
            await asyncio.sleep(0.3)
            hinted = await handle.execute("1+1")
            assert "[REPL memory]" in hinted

            await handle.execute("del x")
            await asyncio.sleep(0.5)  # let RSS actually drop and the observer re-sample
            cleared = await handle.execute("2+2")
            assert "[REPL memory]" not in cleared
        finally:
            await handle.kill()


class TestE2EMemoryBomb:
    async def test_e2e_memory_bomb_kills_worker_not_host(self, report_dir):
        """Spec Integration Tests: hard breach kills the WORKER, not the host —
        host RSS delta stays bounded, and the pool restarts the session
        transparently on the next call (AC6)."""
        config = WorkerConfig(
            deadline_ms=20_000,
            max_workers=2,
            idle_ttl_seconds=30,
            prewarm_pool_size=0,
            observer_poll_ms=100,
            memory_soft_limit_bytes=0,
            memory_hard_limit_bytes=512 * 1024 * 1024,
        )
        tool = PythonREPLTool(report_dir=report_dir, worker_config=config)
        host_proc = psutil.Process()
        rss_before = host_proc.memory_info().rss
        try:
            result = await tool._execute(
                "arrays = []\nfor _ in range(2000):\n    arrays.append(bytearray(1024 * 1024))\n"
            )
            assert isinstance(result, dict)
            assert result["status"] == "error"
            assert "memory" in result["error"]

            rss_after = host_proc.memory_info().rss
            assert (rss_after - rss_before) < 100 * 1024 * 1024, "host process RSS grew too much"

            # Next call transparently gets a fresh, restarted worker — the
            # G5 return-envelope contract is unchanged (str on success).
            recovered = await tool._execute("y = 1\nprint(y)")
            assert isinstance(recovered, str)
            assert "1" in recovered
        finally:
            await _shutdown(tool)
