"""`_consolidate` must fail fast with ``merge_busy`` instead of waiting forever on `_merge_lock`."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import ERROR_CODES, CoderError


def test_merge_busy_is_a_declared_error_code() -> None:
    assert "merge_busy" in ERROR_CODES
    assert CoderError(code="merge_busy", message="x").code == "merge_busy"


@pytest.mark.asyncio
async def test_acquire_merge_lock_times_out_with_merge_busy() -> None:
    holder = SimpleNamespace(_merge_lock=asyncio.Lock())
    await holder._merge_lock.acquire()  # a stalled background consolidation
    with pytest.raises(CoderFailure) as exc_info:
        async with SddCoderEngine._acquire_merge_lock(holder, 0.05):
            pytest.fail("must not enter the critical section")
    assert exc_info.value.code == "merge_busy"
    assert holder._merge_lock.locked(), "the stalled holder keeps the lock; we never touched it"


@pytest.mark.asyncio
async def test_acquire_merge_lock_releases_on_exit_and_on_cancellation() -> None:
    holder = SimpleNamespace(_merge_lock=asyncio.Lock())
    async with SddCoderEngine._acquire_merge_lock(holder):
        assert holder._merge_lock.locked()
    assert not holder._merge_lock.locked()

    async def _stuck() -> None:
        async with SddCoderEngine._acquire_merge_lock(holder):
            await asyncio.sleep(30)

    task = asyncio.create_task(_stuck())
    await asyncio.sleep(0.05)
    assert holder._merge_lock.locked()
    task.cancel()  # what the MCP host's notifications/cancelled turns into
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not holder._merge_lock.locked()


@pytest.mark.asyncio
async def test_background_path_waits_instead_of_failing() -> None:
    """Without a timeout (the `_run_task` job path) the lock is awaited, never `merge_busy`."""
    holder = SimpleNamespace(_merge_lock=asyncio.Lock())
    await holder._merge_lock.acquire()

    async def _waiter() -> str:
        async with SddCoderEngine._acquire_merge_lock(holder):
            return "entered"

    task = asyncio.create_task(_waiter())
    await asyncio.sleep(0.1)
    assert not task.done(), "must still be waiting, not failed"
    holder._merge_lock.release()
    assert await asyncio.wait_for(task, timeout=5) == "entered"


def test_only_the_foreground_merge_bounds_the_lock_wait() -> None:
    """`merge()` passes the timeout; the background `_run_task` job path never does."""
    import inspect

    assert "lock_timeout_s=MERGE_LOCK_TIMEOUT_S" in inspect.getsource(SddCoderEngine.merge)
    assert "lock_timeout_s" not in inspect.getsource(SddCoderEngine._run_task)
