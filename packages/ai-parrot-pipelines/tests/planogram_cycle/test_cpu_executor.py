"""Offline tests for CpuExecutor. Helpers are MODULE-LEVEL so spawn workers can import them."""

import asyncio
import math
import os
import time
from concurrent.futures.process import BrokenProcessPool

import pytest

from parrot_pipelines.planogram.perception.executor import CpuExecutor


def _sleep_and_pid(seconds: float) -> int:
    """Sleep in the worker and return its PID."""
    time.sleep(seconds)
    return os.getpid()


def _boom(message: str) -> None:
    """Raise inside the worker."""
    raise KeyError(message)


def _die() -> None:
    """Kill the worker process abruptly."""
    os._exit(1)


async def test_lazy_pool_and_basic_result():  # AC-1
    """No process before the first run; the result comes back."""
    cpu = CpuExecutor()
    assert cpu._pool is None
    try:
        assert await cpu.run(math.sqrt, 16.0) == 4.0
    finally:
        await cpu.aclose()


async def test_cpu_executor_bounded_and_cancellable():  # AC-2 + AC-3 (spec §4 name)
    """At most max_workers processes/in-flight calls; a cancelled waiter leaves the executor usable."""
    async with CpuExecutor(max_workers=2) as cpu:
        await cpu.run(_sleep_and_pid, 0.0)  # warm the (spawned) workers so start-up is not timed
        start = time.monotonic()
        pids = await asyncio.gather(*(cpu.run(_sleep_and_pid, 0.3) for _ in range(6)))
        elapsed = time.monotonic() - start
        assert len(set(pids)) <= 2
        assert elapsed >= 0.85

        before = asyncio.all_tasks()
        waiter = asyncio.create_task(cpu.run(_sleep_and_pid, 0.5))
        await asyncio.sleep(0.05)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert asyncio.all_tasks() - before == set()
        assert isinstance(await cpu.run(_sleep_and_pid, 0.0), int)


async def test_close_is_idempotent_and_blocks_further_use():  # AC-4
    """aclose twice is fine; run afterwards raises RuntimeError."""
    cpu = CpuExecutor(max_workers=1)
    await cpu.run(math.sqrt, 4.0)
    await cpu.aclose()
    await cpu.aclose()
    assert cpu._pool is None
    with pytest.raises(RuntimeError, match="closed"):
        await cpu.run(math.sqrt, 4.0)


async def test_async_context_manager_closes_on_error():  # AC-4
    """async with closes on exit, including when the body raises."""
    with pytest.raises(ZeroDivisionError):
        async with CpuExecutor(max_workers=1) as cpu:
            await cpu.run(math.sqrt, 9.0)
            raise ZeroDivisionError
    with pytest.raises(RuntimeError):
        await cpu.run(math.sqrt, 9.0)
    async with CpuExecutor(max_workers=1) as clean:
        pass
    assert clean._closed is True


async def test_worker_exception_propagates():  # AC-5
    """An exception raised in the worker keeps its type."""
    async with CpuExecutor(max_workers=1) as cpu:
        with pytest.raises(KeyError):
            await cpu.run(_boom, "x")


def test_rejects_non_positive_workers():  # AC-6
    """max_workers < 1 is rejected."""
    with pytest.raises(ValueError):
        CpuExecutor(max_workers=0)


async def test_broken_pool_is_rebuilt():  # AC-7
    """A dead worker surfaces BrokenProcessPool; the next run uses a fresh pool."""
    async with CpuExecutor(max_workers=1) as cpu:
        with pytest.raises(BrokenProcessPool):
            await cpu.run(_die)
        assert cpu._pool is None
        assert await cpu.run(math.sqrt, 25.0) == 5.0
