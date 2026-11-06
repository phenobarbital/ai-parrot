"""Tests for PageIndex per-tree publication locks."""

import asyncio
import fcntl
import multiprocessing as mp

import pytest

from parrot.knowledge.pageindex.locks import TreeLockTimeout, lock_path, tree_lock


def _hold(path: str, ready, release) -> None:
    """Hold a process lock until the parent signals release."""
    with open(path, "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        ready.set()
        release.wait(10)


@pytest.mark.asyncio
async def test_tree_lock_excludes_second_process(tmp_path) -> None:
    """Raise rather than publish while another process owns the tree lock."""
    path = lock_path(tmp_path, "t")
    path.parent.mkdir(parents=True)
    ctx = mp.get_context("spawn")
    ready, release = ctx.Event(), ctx.Event()
    proc = ctx.Process(target=_hold, args=(str(path), ready, release))
    proc.start()
    try:
        assert ready.wait(10)
        with pytest.raises(TreeLockTimeout):
            async with tree_lock(tmp_path, "t", timeout=0.2):
                pass
    finally:
        release.set()
        proc.join(10)

    assert proc.exitcode == 0


@pytest.mark.asyncio
async def test_tree_lock_serializes_coroutines(tmp_path) -> None:
    """Serialize local waiters before they contend for the process lock."""
    events: list[str] = []
    first_entered = asyncio.Event()

    async def first() -> None:
        async with tree_lock(tmp_path, "t", timeout=1):
            events.append("first-enter")
            first_entered.set()
            await asyncio.sleep(0.1)
            events.append("first-exit")

    async def second() -> None:
        await first_entered.wait()
        async with tree_lock(tmp_path, "t", timeout=1):
            events.append("second-enter")

    await asyncio.gather(first(), second())

    assert events == ["first-enter", "first-exit", "second-enter"]


@pytest.mark.asyncio
async def test_tree_lock_times_out_for_local_waiter(tmp_path) -> None:
    """Apply the timeout budget while waiting on an in-process lock."""
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with tree_lock(tmp_path, "t", timeout=1):
            entered.set()
            await release.wait()

    task = asyncio.create_task(holder())
    await entered.wait()
    try:
        with pytest.raises(TreeLockTimeout):
            async with tree_lock(tmp_path, "t", timeout=0.01):
                pass
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_tree_lock_releases_on_exception(tmp_path) -> None:
    """Release the file and local locks when the protected block raises."""
    with pytest.raises(ValueError):
        async with tree_lock(tmp_path, "t", timeout=1):
            raise ValueError("expected")

    async with tree_lock(tmp_path, "t", timeout=0):
        pass


def test_lock_path_rejects_bad_name(tmp_path) -> None:
    """Reject an unsafe name before creating a lock-file path."""
    with pytest.raises(ValueError):
        lock_path(tmp_path, "../x")
