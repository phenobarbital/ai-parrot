"""``WorkerPool`` lifecycle tests for FEAT-380 Module 4 (AC10/AC12).

Real worker subprocesses are spawned throughout, so every fixture uses a
generous `RLIMIT_AS` (spec default ~4 GiB) — see `test_worker.py`'s
`real_worker_config` reasoning: `PythonREPLTool` imports pandas/numpy/
matplotlib, which fail to `mmap` their compiled extensions under the spec's
illustrative 512 MiB "fast tests" fixture.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import importlib
import logging
import time

import pytest

from parrot.tools.repl_worker import pool as pool_module
from parrot.tools.repl_worker.pool import WorkerPool, WorkerPoolExhaustedError
from parrot.tools.repl_worker.protocol import WorkerConfig

abstract_module = importlib.import_module("parrot.tools.abstract")


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    """A per-test report dir that passes `AbstractTool`'s output_dir guard.

    Both halves are needed: `abstract_module.STATIC_DIR` is patched for THIS
    (parent/test) process, and the `STATIC_DIR` env var is set for any
    spawned WORKER subprocess (which re-imports `parrot.conf` fresh and
    inherits the parent's environment) — see `test_interrupt.py`'s
    `report_dir` fixture docstring for the full finding (FEAT-521 TASK-2781).
    """
    monkeypatch.setattr(abstract_module, "STATIC_DIR", tmp_path)
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    return str(tmp_path)


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
    async def test_pool_ceiling_rejects(self, worker_config, report_dir):
        """3rd concurrent session with max_workers=2 -> WorkerPoolExhaustedError immediately (AC12)."""
        pool = WorkerPool(worker_config, output_dir=report_dir)
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

    async def test_two_sessions_get_distinct_workers(self, worker_config, report_dir):
        pool = WorkerPool(worker_config, output_dir=report_dir)
        try:
            handle_a = await pool.acquire("a")
            handle_b = await pool.acquire("b")
            assert handle_a is not handle_b
        finally:
            await pool.shutdown()

    async def test_acquire_same_session_returns_same_handle(self, worker_config, report_dir):
        pool = WorkerPool(worker_config, output_dir=report_dir)
        try:
            first = await pool.acquire("a")
            second = await pool.acquire("a")
            assert first is second
        finally:
            await pool.shutdown()

    async def test_pool_ttl_eviction(self, report_dir):
        """Worker idle > TTL is evicted; re-acquire spawns a fresh one (AC12)."""
        config = WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=3, prewarm_pool_size=0)
        pool = WorkerPool(config, output_dir=report_dir)
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

    async def test_pool_prewarm(self, report_dir):
        """A prewarmed worker is assigned without paying the pandas import (AC10)."""
        config = WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=30, prewarm_pool_size=1)
        pool = WorkerPool(config, output_dir=report_dir)
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

    async def test_crash_restart(self, worker_config, report_dir):
        """Externally-killed worker -> next acquire yields a live replacement."""
        pool = WorkerPool(worker_config, output_dir=report_dir)
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

    async def test_orphan_reaping(self, worker_config, report_dir):
        """shutdown() leaves zero live workers, including prewarmed spares (AC12)."""
        config = WorkerConfig(deadline_ms=5_000, max_workers=4, idle_ttl_seconds=30, prewarm_pool_size=1)
        pool = WorkerPool(config, output_dir=report_dir)
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

    async def test_pool_spare_not_ready_until_ready_frame(self, report_dir, caplog):
        """`_prewarmed` stays empty while the worker boots, and the log follows the frame."""
        caplog.set_level(logging.DEBUG, logger="parrot.tools.repl_worker.pool")
        config = WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=30, prewarm_pool_size=1)
        pool = WorkerPool(config, output_dir=report_dir, repl_kwargs=SLOW_BOOTSTRAP)
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

    async def test_pool_spare_failing_bootstrap_is_never_appended(self, report_dir):
        """A spare that misses its bootstrap budget is dropped, not pooled."""
        config = WorkerConfig(
            deadline_ms=5_000,
            max_workers=2,
            idle_ttl_seconds=30,
            prewarm_pool_size=1,
            bootstrap_timeout_ms=500,
        )
        pool = WorkerPool(config, output_dir=report_dir, repl_kwargs=SLOW_BOOTSTRAP)
        try:
            await pool._ensure_started()
            await asyncio.sleep(3.0)  # past the 500 ms budget and the 3 s sleep
            assert pool._prewarmed == []
        finally:
            await pool.shutdown()


class TestRestartLoopVisibility:
    """FEAT-500 G5/AC8: a session that keeps burning workers says so."""

    async def test_pool_restart_loop_warning(self, worker_config, report_dir, caplog):
        caplog.set_level(logging.WARNING, logger="parrot.tools.repl_worker.pool")
        pool = WorkerPool(worker_config, output_dir=report_dir)
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

    async def test_restart_count_unknown_session_is_zero(self, worker_config, report_dir):
        pool = WorkerPool(worker_config, output_dir=report_dir)
        try:
            assert pool.restart_count("never-seen") == 0
        finally:
            await pool.shutdown()


class TestShutdownDuringBootstrap:
    """Code-review finding (FEAT-500 AC12): no worker may outlive the pool."""

    async def test_shutdown_while_spare_is_booting_kills_it(self, report_dir):
        """A top-up cancelled mid-`wait_ready()` must not leak its worker.

        The handle is not in `_prewarmed` yet, so `shutdown()`'s sweep over
        `_sessions + _prewarmed` cannot see it; the cancelled top-up itself is
        the only thing that can kill it.
        """
        config = WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=30, prewarm_pool_size=1)
        pool = WorkerPool(config, output_dir=report_dir, repl_kwargs=SLOW_BOOTSTRAP)

        spawned = []
        real_spawn = pool._spawn_handle

        async def tracking_spawn():
            handle = await real_spawn()
            spawned.append(handle)
            return handle

        pool._spawn_handle = tracking_spawn

        await pool._ensure_started()
        for _ in range(50):  # wait until the spare is spawned but still booting
            await asyncio.sleep(0.1)
            if spawned:
                break
        assert spawned, "no worker was spawned"
        assert pool._prewarmed == [], "spare should still be booting"

        await pool.shutdown()

        assert all(
            not handle.is_alive for handle in spawned
        ), "a worker spawned but not yet prewarmed outlived shutdown()"


class TestCeilingUnderBootstrap:
    """Code-review finding (FEAT-500): the ceiling must hold across the readiness wait."""

    async def test_ceiling_not_exceeded_while_a_spare_is_booting(self, report_dir):
        """A spare that becomes surplus while booting is discarded, not adopted.

        `_top_up_prewarmed()` releases the lock for `_spawn_handle()` +
        `wait_ready()` (up to `bootstrap_timeout_ms`). A concurrent `acquire()`
        spawning off that stale count used to push the pool to
        `max_workers + 1`.
        """
        config = WorkerConfig(deadline_ms=5_000, max_workers=1, idle_ttl_seconds=30, prewarm_pool_size=1)
        pool = WorkerPool(config, output_dir=report_dir, repl_kwargs=SLOW_BOOTSTRAP)
        try:
            await pool._ensure_started()
            await asyncio.sleep(0.3)  # spare is spawned but still bootstrapping
            assert pool._prewarmed == []

            await pool.acquire("session-a")  # spawns fresh off the stale count

            for _ in range(60):  # let the top-up finish and decide
                await asyncio.sleep(0.1)
                if pool._prewarmed:
                    break

            total = len(pool._sessions) + len(pool._prewarmed)
            assert total <= pool._ceiling, f"pool holds {total} workers, ceiling is {pool._ceiling}"
        finally:
            await pool.shutdown()


class TestExecutorSizingWarning:
    """Code-review suggestion (FEAT-500): surface an undersized shared executor."""

    def test_warns_when_executor_cannot_serve_every_worker(self, report_dir, caplog):
        caplog.set_level(logging.WARNING, logger="parrot.tools.repl_worker.pool")
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            config = WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=30, prewarm_pool_size=2)
            WorkerPool(config, output_dir=report_dir, executor=executor)
            assert "shared executor has 1 thread(s)" in caplog.text
            assert "up to 4 live worker(s)" in caplog.text
        finally:
            executor.shutdown(wait=False)

    def test_no_warning_when_executor_is_large_enough(self, report_dir, caplog):
        caplog.set_level(logging.WARNING, logger="parrot.tools.repl_worker.pool")
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)
        try:
            config = WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=30, prewarm_pool_size=2)
            WorkerPool(config, output_dir=report_dir, executor=executor)
            assert "shared executor has" not in caplog.text
        finally:
            executor.shutdown(wait=False)

    def test_no_warning_without_an_executor(self, report_dir, caplog):
        """The default (no executor passed) must stay silent."""
        caplog.set_level(logging.WARNING, logger="parrot.tools.repl_worker.pool")
        config = WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=30, prewarm_pool_size=2)
        WorkerPool(config, output_dir=report_dir)
        assert "shared executor has" not in caplog.text


class TestCgroupV2Availability:
    """FEAT-521 §7 Q3: cgroup v2 memory.max/memory.current, capped by psutil."""

    def test_finite_cgroup_limit(self, tmp_path, monkeypatch):
        max_file = tmp_path / "memory.max"
        current_file = tmp_path / "memory.current"
        max_file.write_text("1000000\n")
        current_file.write_text("400000\n")
        monkeypatch.setattr(pool_module, "_CGROUP_MEMORY_MAX", max_file)
        monkeypatch.setattr(pool_module, "_CGROUP_MEMORY_CURRENT", current_file)
        assert pool_module._cgroup_v2_available_bytes() == 600_000

    def test_unlimited_cgroup_falls_back_to_none(self, tmp_path, monkeypatch):
        max_file = tmp_path / "memory.max"
        current_file = tmp_path / "memory.current"
        max_file.write_text("max\n")
        current_file.write_text("400000\n")
        monkeypatch.setattr(pool_module, "_CGROUP_MEMORY_MAX", max_file)
        monkeypatch.setattr(pool_module, "_CGROUP_MEMORY_CURRENT", current_file)
        assert pool_module._cgroup_v2_available_bytes() is None

    def test_missing_cgroup_files_fall_back_to_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pool_module, "_CGROUP_MEMORY_MAX", tmp_path / "does-not-exist")
        monkeypatch.setattr(pool_module, "_CGROUP_MEMORY_CURRENT", tmp_path / "also-missing")
        assert pool_module._cgroup_v2_available_bytes() is None

    def test_malformed_cgroup_value_falls_back_to_none(self, tmp_path, monkeypatch):
        max_file = tmp_path / "memory.max"
        current_file = tmp_path / "memory.current"
        max_file.write_text("not-a-number\n")
        current_file.write_text("400000\n")
        monkeypatch.setattr(pool_module, "_CGROUP_MEMORY_MAX", max_file)
        monkeypatch.setattr(pool_module, "_CGROUP_MEMORY_CURRENT", current_file)
        assert pool_module._cgroup_v2_available_bytes() is None

    def test_effective_available_bytes_uses_the_tighter_of_the_two(self, tmp_path, monkeypatch):
        max_file = tmp_path / "memory.max"
        current_file = tmp_path / "memory.current"
        max_file.write_text("1000\n")
        current_file.write_text("0\n")  # cgroup available = 1000
        monkeypatch.setattr(pool_module, "_CGROUP_MEMORY_MAX", max_file)
        monkeypatch.setattr(pool_module, "_CGROUP_MEMORY_CURRENT", current_file)
        fake_vm = type("VM", (), {"available": 999_999_999})()
        monkeypatch.setattr(pool_module.psutil, "virtual_memory", lambda: fake_vm)
        assert pool_module._effective_host_available_bytes() == 1000

    def test_effective_available_bytes_ignores_unlimited_cgroup(self, tmp_path, monkeypatch):
        max_file = tmp_path / "memory.max"
        current_file = tmp_path / "memory.current"
        max_file.write_text("max\n")
        current_file.write_text("0\n")
        monkeypatch.setattr(pool_module, "_CGROUP_MEMORY_MAX", max_file)
        monkeypatch.setattr(pool_module, "_CGROUP_MEMORY_CURRENT", current_file)
        fake_vm = type("VM", (), {"available": 555})()
        monkeypatch.setattr(pool_module.psutil, "virtual_memory", lambda: fake_vm)
        assert pool_module._effective_host_available_bytes() == 555


class TestHostMemoryReserve:
    """FEAT-521 G5: the pool refuses to spawn/prewarm below the host reserve."""

    async def test_acquire_respects_host_reserve(self, report_dir, monkeypatch):
        """AC: `acquire()` raises a memory-pressure `WorkerPoolExhaustedError`
        only when it would SPAWN — no worker is created."""
        monkeypatch.setattr(pool_module, "_effective_host_available_bytes", lambda: 0)
        config = WorkerConfig(
            deadline_ms=5_000,
            max_workers=2,
            idle_ttl_seconds=5,
            prewarm_pool_size=0,
            host_memory_reserve_bytes=2 * 1024**3,
        )
        pool = WorkerPool(config, output_dir=report_dir)
        try:
            with pytest.raises(WorkerPoolExhaustedError, match="memory"):
                await pool.acquire("a")
            assert pool._sessions == {}
        finally:
            await pool.shutdown()

    async def test_prewarm_skipped_under_pressure(self, report_dir, monkeypatch, caplog):
        """AC: `_top_up_prewarmed()` returns without spawning, DEBUG log."""
        caplog.set_level(logging.DEBUG, logger="parrot.tools.repl_worker.pool")
        monkeypatch.setattr(pool_module, "_effective_host_available_bytes", lambda: 0)
        config = WorkerConfig(
            deadline_ms=5_000,
            max_workers=2,
            idle_ttl_seconds=30,
            prewarm_pool_size=1,
            host_memory_reserve_bytes=2 * 1024**3,
        )
        pool = WorkerPool(config, output_dir=report_dir)
        try:
            pool._started = True  # _top_up_prewarmed() no-ops before start() otherwise
            await pool._top_up_prewarmed()
            assert pool._prewarmed == []
            assert "skipping prewarm top-up" in caplog.text
        finally:
            await pool.shutdown()

    async def test_reserve_does_not_block_an_existing_session(self, report_dir, monkeypatch):
        """A live session's worker keeps working even while the host is under pressure."""
        config = WorkerConfig(
            deadline_ms=5_000,
            max_workers=2,
            idle_ttl_seconds=30,
            prewarm_pool_size=0,
            host_memory_reserve_bytes=2 * 1024**3,
        )
        pool = WorkerPool(config, output_dir=report_dir)
        try:
            handle = await pool.acquire("a")
            monkeypatch.setattr(pool_module, "_effective_host_available_bytes", lambda: 0)
            again = await pool.acquire("a")
            assert again is handle
            assert again.is_alive is True
        finally:
            await pool.shutdown()

    async def test_reserve_does_not_block_consuming_a_prewarmed_spare(self, report_dir, monkeypatch):
        """Consuming a spare converts it into a session slot — spawns nothing —
        so it must never be blocked by the reserve check."""
        config = WorkerConfig(
            deadline_ms=5_000,
            max_workers=2,
            idle_ttl_seconds=30,
            prewarm_pool_size=1,
            host_memory_reserve_bytes=2 * 1024**3,
        )
        pool = WorkerPool(config, output_dir=report_dir)
        try:
            await pool._ensure_started()
            for _ in range(100):
                if pool._prewarmed:
                    break
                await asyncio.sleep(0.1)
            assert pool._prewarmed, "prewarmed worker did not spawn in time"

            monkeypatch.setattr(pool_module, "_effective_host_available_bytes", lambda: 0)
            handle = await pool.acquire("a")
            assert handle.is_alive is True
        finally:
            await pool.shutdown()


class TestPressureEviction:
    """FEAT-521 G5: pressure eviction kills prewarmed spares, never bound sessions."""

    async def test_pressure_evicts_spares_not_sessions(self, worker_config, report_dir, monkeypatch):
        config = WorkerConfig(
            deadline_ms=5_000,
            max_workers=3,
            idle_ttl_seconds=30,
            prewarm_pool_size=1,
            host_memory_reserve_bytes=1,
        )
        pool = WorkerPool(config, output_dir=report_dir)
        try:
            handle = await pool.acquire("a")
            await pool._ensure_started()
            for _ in range(100):
                if pool._prewarmed:
                    break
                await asyncio.sleep(0.1)
            assert pool._prewarmed, "prewarmed spare did not spawn in time"
            spare = pool._prewarmed[0]

            monkeypatch.setattr(pool_module, "_effective_host_available_bytes", lambda: 0)
            await pool._evict_under_pressure()

            assert pool._prewarmed == []
            assert spare.is_alive is False
            assert handle.is_alive is True
            assert "a" in pool._sessions
        finally:
            await pool.shutdown()

    async def test_no_eviction_when_above_reserve(self, report_dir, monkeypatch):
        config = WorkerConfig(
            deadline_ms=5_000,
            max_workers=2,
            idle_ttl_seconds=30,
            prewarm_pool_size=1,
            host_memory_reserve_bytes=2 * 1024**3,
        )
        pool = WorkerPool(config, output_dir=report_dir)
        try:
            await pool._ensure_started()
            for _ in range(100):
                if pool._prewarmed:
                    break
                await asyncio.sleep(0.1)
            assert pool._prewarmed

            monkeypatch.setattr(pool_module, "_effective_host_available_bytes", lambda: 999_999_999_999)
            await pool._evict_under_pressure()
            assert len(pool._prewarmed) == 1
        finally:
            await pool.shutdown()


class TestMemoryTelemetry:
    """FEAT-521 §3 Module 5: memory_summary() and aggregate/restart logging."""

    async def test_memory_summary_reflects_observer_samples(self, worker_config, report_dir):
        pool = WorkerPool(worker_config, output_dir=report_dir)
        try:
            await pool.acquire("a")
            handle = pool._sessions["a"]
            await handle.execute("x = 1")
            for _ in range(50):
                if handle.observer is not None and handle.observer.last() is not None:
                    break
                await asyncio.sleep(0.1)

            summary = pool.memory_summary()
            assert summary["workers"] == 1
            assert summary["rss_total"] > 0
            assert summary["host_available"] > 0
        finally:
            await pool.shutdown()

    async def test_aggregate_rss_logged_at_info_when_soft_breached(self, report_dir, caplog):
        caplog.set_level(logging.INFO, logger="parrot.tools.repl_worker.pool")
        config = WorkerConfig(
            deadline_ms=20_000,
            max_workers=2,
            idle_ttl_seconds=30,
            prewarm_pool_size=0,
            observer_poll_ms=100,
            memory_soft_limit_bytes=320 * 1024 * 1024,
            memory_hard_limit_bytes=0,
        )
        pool = WorkerPool(config, output_dir=report_dir)
        try:
            handle = await pool.acquire("a")
            await handle.execute("x = bytearray(150 * 1024 * 1024)")
            for _ in range(50):
                if handle.observer is not None and handle.observer.memory_pressure is not None:
                    break
                await asyncio.sleep(0.1)
            pool._log_aggregate_rss_if_pressured()
            assert "aggregate RSS" in caplog.text
        finally:
            await pool.shutdown()

    async def test_no_aggregate_log_when_nothing_pressured(self, worker_config, report_dir, caplog):
        caplog.set_level(logging.INFO, logger="parrot.tools.repl_worker.pool")
        pool = WorkerPool(worker_config, output_dir=report_dir)
        try:
            await pool.acquire("a")
            pool._log_aggregate_rss_if_pressured()
            assert "aggregate RSS" not in caplog.text
        finally:
            await pool.shutdown()

    async def test_restart_log_includes_memory_cause(self, report_dir, caplog):
        """FEAT-521: `_record_restart()`'s WARNING names the observer's memory cause."""
        caplog.set_level(logging.WARNING, logger="parrot.tools.repl_worker.pool")
        config = WorkerConfig(
            deadline_ms=5_000,
            max_workers=2,
            idle_ttl_seconds=30,
            prewarm_pool_size=0,
            observer_poll_ms=100,
            memory_soft_limit_bytes=0,
            memory_hard_limit_bytes=300 * 1024 * 1024,
        )
        pool = WorkerPool(config, output_dir=report_dir)
        try:
            for _ in range(3):
                handle = await pool.acquire("s1")
                await handle.wait_ready()
                await handle.execute("x = bytearray(350 * 1024 * 1024)")
                for _ in range(50):
                    if not handle.is_alive:
                        break
                    await asyncio.sleep(0.1)
                assert handle.is_alive is False
            await pool.acquire("s1")  # observes the 3rd death -> logs the loop warning

            assert pool.restart_count("s1") == 3
            assert "possible restart loop" in caplog.text
            assert "memory cause" in caplog.text
        finally:
            await pool.shutdown()
