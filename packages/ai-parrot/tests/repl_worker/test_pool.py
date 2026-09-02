"""``WorkerPool`` lifecycle tests for FEAT-380 Module 4 (AC10/AC12).

Real worker subprocesses are spawned throughout, so every fixture uses a
generous `RLIMIT_AS` (spec default ~4 GiB) — see `test_worker.py`'s
`real_worker_config` reasoning: `PythonREPLTool` imports pandas/numpy/
matplotlib, which fail to `mmap` their compiled extensions under the spec's
illustrative 512 MiB "fast tests" fixture.
"""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

from parrot.tools.repl_worker.pool import WorkerPool, WorkerPoolExhaustedError
from parrot.tools.repl_worker.protocol import WorkerConfig


@pytest.fixture
def worker_config():
    """Tiny ceiling, short TTL, no prewarm — mirrors the spec's fixture,
    with a real-worker-sized RLIMIT_AS (see module docstring)."""
    return WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=5, prewarm_pool_size=0)


#: Delays the WORKER's own bootstrap deterministically (FEAT-500): mirrored
#: into the child via `repl_kwargs` and run by its own
#: `PythonREPLTool._bootstrap()`. No test hook in production code.
SLOW_BOOTSTRAP = {"setup_code": "import time\ntime.sleep(3)"}


class TestWorkerPool:
    async def test_pool_ceiling_rejects(self, worker_config, tmp_path):
        """3rd concurrent session with max_workers=2 -> WorkerPoolExhaustedError immediately (AC12)."""
        pool = WorkerPool(worker_config, output_dir=str(tmp_path))
        try:
            await pool.acquire("a")
            await pool.acquire("b")

            start = time.monotonic()
            with pytest.raises(WorkerPoolExhaustedError):
                await pool.acquire("c")
            elapsed = time.monotonic() - start
            # Rejected immediately — no queueing/waiting on a free slot.
            assert elapsed < 1.0
        finally:
            await pool.shutdown()

    async def test_two_sessions_get_distinct_workers(self, worker_config, tmp_path):
        pool = WorkerPool(worker_config, output_dir=str(tmp_path))
        try:
            handle_a = await pool.acquire("a")
            handle_b = await pool.acquire("b")
            assert handle_a is not handle_b
        finally:
            await pool.shutdown()

    async def test_acquire_same_session_returns_same_handle(self, worker_config, tmp_path):
        pool = WorkerPool(worker_config, output_dir=str(tmp_path))
        try:
            first = await pool.acquire("a")
            second = await pool.acquire("a")
            assert first is second
        finally:
            await pool.shutdown()

    async def test_pool_ttl_eviction(self, tmp_path):
        """Worker idle > TTL is evicted; re-acquire spawns a fresh one (AC12)."""
        config = WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=3, prewarm_pool_size=0)
        pool = WorkerPool(config, output_dir=str(tmp_path))
        try:
            handle1 = await pool.acquire("a")
            assert handle1.is_alive

            # Wait past the TTL + one maintenance-sweep interval.
            await asyncio.sleep(config.idle_ttl_seconds + 2)

            assert handle1.is_alive is False

            handle2 = await pool.acquire("a")
            assert handle2 is not handle1
            assert handle2.is_alive
        finally:
            await pool.shutdown()

    async def test_pool_prewarm(self, tmp_path):
        """A prewarmed worker is assigned without paying the pandas import (AC10)."""
        config = WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=30, prewarm_pool_size=1)
        pool = WorkerPool(config, output_dir=str(tmp_path))
        try:
            await pool._ensure_started()
            # Give the background prewarm task time to finish booting
            # (pandas/numpy/matplotlib import).
            for _ in range(100):
                if pool._prewarmed:
                    break
                await asyncio.sleep(0.1)
            assert pool._prewarmed, "prewarmed worker did not spawn in time"

            start = time.monotonic()
            handle = await pool.acquire("a")
            elapsed = time.monotonic() - start

            # No import cost paid on this call — assignment only.
            assert elapsed < 0.5
            result = await handle.execute("x = 1")
            assert isinstance(result, str)
        finally:
            await pool.shutdown()

    async def test_crash_restart(self, worker_config, tmp_path):
        """Externally-killed worker -> next acquire yields a live replacement."""
        pool = WorkerPool(worker_config, output_dir=str(tmp_path))
        try:
            handle1 = await pool.acquire("a")
            await handle1.kill()
            assert handle1.is_alive is False

            handle2 = await pool.acquire("a")
            assert handle2 is not handle1
            assert handle2.is_alive
            result = await handle2.execute("x = 1")
            assert isinstance(result, str)
        finally:
            await pool.shutdown()

    async def test_orphan_reaping(self, worker_config, tmp_path):
        """shutdown() leaves zero live workers, including prewarmed spares (AC12)."""
        config = WorkerConfig(
            deadline_ms=5_000, max_workers=4, idle_ttl_seconds=30, prewarm_pool_size=1
        )
        pool = WorkerPool(config, output_dir=str(tmp_path))
        handle_a = await pool.acquire("a")
        handle_b = await pool.acquire("b")

        await pool._ensure_started()
        for _ in range(50):
            if pool._prewarmed:
                break
            await asyncio.sleep(0.1)
        prewarmed_handles = list(pool._prewarmed)

        await pool.shutdown()

        assert handle_a.is_alive is False
        assert handle_b.is_alive is False
        for handle in prewarmed_handles:
            assert handle.is_alive is False


class TestReadinessGate:
    """FEAT-500 G1/AC1: a spare only counts as prewarmed once it is READY."""

    async def test_pool_spare_not_ready_until_ready_frame(self, tmp_path, caplog):
        """`_prewarmed` stays empty while the worker boots, and the log follows the frame."""
        caplog.set_level(logging.DEBUG, logger="parrot.tools.repl_worker.pool")
        config = WorkerConfig(
            deadline_ms=5_000, max_workers=2, idle_ttl_seconds=30, prewarm_pool_size=1
        )
        pool = WorkerPool(config, output_dir=str(tmp_path), repl_kwargs=SLOW_BOOTSTRAP)
        try:
            await pool._ensure_started()
            await asyncio.sleep(0.5)
            # The old code appended (and logged "ready") in the same
            # millisecond as the spawn — this is the regression guard.
            assert pool._prewarmed == []
            assert "prewarmed worker ready" not in caplog.text

            for _ in range(80):  # <= 8 s
                await asyncio.sleep(0.1)
                if pool._prewarmed:
                    break
            assert len(pool._prewarmed) == 1
            assert pool._prewarmed[0].is_ready is True
            assert "prewarmed worker ready" in caplog.text
        finally:
            await pool.shutdown()

    async def test_pool_spare_failing_bootstrap_is_never_appended(self, tmp_path):
        """A spare that misses its bootstrap budget is dropped, not pooled."""
        config = WorkerConfig(
            deadline_ms=5_000,
            max_workers=2,
            idle_ttl_seconds=30,
            prewarm_pool_size=1,
            bootstrap_timeout_ms=500,
        )
        pool = WorkerPool(config, output_dir=str(tmp_path), repl_kwargs=SLOW_BOOTSTRAP)
        try:
            await pool._ensure_started()
            await asyncio.sleep(3.0)  # past the 500 ms budget and the 3 s sleep
            assert pool._prewarmed == []
        finally:
            await pool.shutdown()


class TestRestartLoopVisibility:
    """FEAT-500 G5/AC8: a session that keeps burning workers says so."""

    async def test_pool_restart_loop_warning(self, worker_config, tmp_path, caplog):
        caplog.set_level(logging.WARNING, logger="parrot.tools.repl_worker.pool")
        pool = WorkerPool(worker_config, output_dir=str(tmp_path))
        try:
            for _ in range(3):
                handle = await pool.acquire("s1")
                await handle.wait_ready()
                await handle.kill()  # external death
                await pool.acquire("s1")  # observes the death -> one restart

            assert pool.restart_count("s1") == 3
            assert caplog.text.count("possible restart loop") == 1
            assert "'s1'" in caplog.text
        finally:
            await pool.shutdown()

    async def test_restart_count_unknown_session_is_zero(self, worker_config, tmp_path):
        pool = WorkerPool(worker_config, output_dir=str(tmp_path))
        try:
            assert pool.restart_count("never-seen") == 0
        finally:
            await pool.shutdown()
