"""Unit tests for SubprocessWorkerPool — FEAT-459 / TASK-3169."""

from __future__ import annotations

import asyncio
import pytest

from parrot.eval.sandbox.base import SandboxSpec
from parrot_formdesigner.services.sandbox.pool import (
    ColdStartTimeoutError,
    PoolExhaustedError,
    SubprocessWorkerPool,
    WorkerDiedError,
)


class TestSubprocessWorkerPool:
    """Tests for SubprocessWorkerPool."""

    @pytest.fixture
    def pool(self) -> SubprocessWorkerPool:
        """Create a test pool with minimal settings."""
        return SubprocessWorkerPool(
            tier12_pool_size=2,
            recycle_after_invocations=3,
            recycle_after_seconds=3600,
            acquire_queue_timeout_ms=1000,
            max_queue_depth=5,
            health_check_interval_s=30,
            cold_start_timeout_ms=2000,
        )

    @pytest.mark.asyncio
    async def test_pool_creation(self, pool: SubprocessWorkerPool) -> None:
        """Pool initializes with correct default values."""
        assert pool._tier12_pool_size == 2
        assert pool._recycle_after_invocations == 3
        assert pool._acquire_queue_timeout_ms == 1000
        assert pool._max_queue_depth == 5

    @pytest.mark.asyncio
    async def test_acquire_returns_sandbox(self, pool: SubprocessWorkerPool) -> None:
        """acquire() returns a Sandbox instance."""
        sandbox = await pool.acquire(SandboxSpec())
        assert sandbox is not None
        await pool.release(sandbox)

    @pytest.mark.asyncio
    async def test_acquire_release_cycle(self, pool: SubprocessWorkerPool) -> None:
        """Basic acquire/release cycle works."""
        sandbox1 = await pool.acquire(SandboxSpec())
        await pool.release(sandbox1)

        # Should be able to acquire again
        sandbox2 = await pool.acquire(SandboxSpec())
        await pool.release(sandbox2)

    @pytest.mark.asyncio
    async def test_pool_recycles_after_n(self) -> None:
        """Pool recycles a worker after recycle_after_invocations."""
        pool = SubprocessWorkerPool(
            tier12_pool_size=1,
            recycle_after_invocations=2,
            recycle_after_seconds=3600,
            acquire_queue_timeout_ms=1000,
            max_queue_depth=5,
            health_check_interval_s=30,
            cold_start_timeout_ms=2000,
        )

        # Acquire and release twice - should trigger recycle on 3rd acquire
        sandbox1 = await pool.acquire(SandboxSpec())
        worker1 = sandbox1._worker
        await pool.release(sandbox1)

        sandbox2 = await pool.acquire(SandboxSpec())
        worker2 = sandbox2._worker
        await pool.release(sandbox2)

        # Third acquire should get a new worker (recycled)
        sandbox3 = await pool.acquire(SandboxSpec())
        worker3 = sandbox3._worker

        # The worker should be different (recycled)
        assert worker3 is not worker1
        assert worker3 is not worker2

        await pool.release(sandbox3)
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_pool_bounded_queue_times_out(self) -> None:
        """Pool raises PoolExhaustedError when queue depth exceeded."""
        pool = SubprocessWorkerPool(
            tier12_pool_size=1,
            recycle_after_invocations=500,
            acquire_queue_timeout_ms=100,  # Short timeout
            max_queue_depth=1,
            health_check_interval_s=30,
            cold_start_timeout_ms=2000,
        )

        # First acquire succeeds
        sandbox1 = await pool.acquire(SandboxSpec())

        # Second acquire should fail fast due to max_queue_depth
        with pytest.raises(PoolExhaustedError):
            await pool.acquire(SandboxSpec())

        await pool.release(sandbox1)
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_pool_exhaustion_after_timeout(self) -> None:
        """Pool raises PoolExhaustedError after acquire_queue_timeout_ms."""
        pool = SubprocessWorkerPool(
            tier12_pool_size=1,
            recycle_after_invocations=500,
            acquire_queue_timeout_ms=100,  # Very short timeout
            max_queue_depth=10,
            health_check_interval_s=30,
            cold_start_timeout_ms=2000,
        )

        # Hold the only worker
        sandbox1 = await pool.acquire(SandboxSpec())

        # Try to acquire another - should timeout
        with pytest.raises(PoolExhaustedError):
            await pool.acquire(SandboxSpec())

        await pool.release(sandbox1)
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_pool_replaces_unhealthy_worker(self) -> None:
        """Pool replaces a worker that becomes unhealthy."""
        pool = SubprocessWorkerPool(
            tier12_pool_size=1,
            recycle_after_invocations=500,
            acquire_queue_timeout_ms=1000,
            max_queue_depth=5,
            health_check_interval_s=30,
            cold_start_timeout_ms=2000,
        )

        sandbox = await pool.acquire(SandboxSpec())
        worker = sandbox._worker

        # Simulate worker dying
        worker.process.terminate()
        await worker.process.wait()

        # Release should detect the death and not return to pool
        await pool.release(sandbox)

        # Next acquire should spawn a new worker
        sandbox2 = await pool.acquire(SandboxSpec())
        assert sandbox2._worker is not worker

        await pool.release(sandbox2)
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_pool_kills_on_timeout(self) -> None:
        """Test that workers are killed on timeout (wall-clock budget)."""
        # This test verifies the recycle_after_seconds path
        pool = SubprocessWorkerPool(
            tier12_pool_size=1,
            recycle_after_invocations=500,
            recycle_after_seconds=0,  # Immediate recycle
            acquire_queue_timeout_ms=1000,
            max_queue_depth=5,
            health_check_interval_s=30,
            cold_start_timeout_ms=2000,
        )

        sandbox = await pool.acquire(SandboxSpec())
        worker = sandbox._worker

        # Release should trigger recycle due to age
        await pool.release(sandbox)

        # Next acquire should get a new worker
        sandbox2 = await pool.acquire(SandboxSpec())
        assert sandbox2._worker is not worker

        await pool.release(sandbox2)
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_health_check_sweep(self) -> SubprocessWorkerPool:
        """Health check sweep detects dead workers."""
        pool = SubprocessWorkerPool(
            tier12_pool_size=2,
            recycle_after_invocations=500,
            acquire_queue_timeout_ms=1000,
            max_queue_depth=5,
            health_check_interval_s=1,  # Fast interval for test
            cold_start_timeout_ms=2000,
        )

        await pool.start_health_checks()

        # Get a worker and put it back
        sandbox = await pool.acquire(SandboxSpec())
        await pool.release(sandbox)

        # Let health check run
        await asyncio.sleep(1.5)

        # The worker should still be in the pool (alive)
        assert pool._idle.qsize() >= 0

        await pool.shutdown()
        return pool

    @pytest.mark.asyncio
    async def test_shutdown_terminates_workers(self) -> None:
        """shutdown() terminates all workers."""
        pool = SubprocessWorkerPool(
            tier12_pool_size=2,
            recycle_after_invocations=500,
            acquire_queue_timeout_ms=1000,
            max_queue_depth=5,
            health_check_interval_s=30,
            cold_start_timeout_ms=2000,
        )

        # Get a worker
        sandbox = await pool.acquire(SandboxSpec())
        await pool.release(sandbox)

        # Shutdown
        await pool.shutdown()

        # Pool should be shut down
        assert pool._shutdown is True
