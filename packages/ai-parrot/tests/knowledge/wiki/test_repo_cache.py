"""Hermetic behavioral tests for the repository cache lock (FEAT-672)."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import time
from pathlib import Path

import pytest

from parrot.knowledge.wiki import repo_cache
from parrot.knowledge.wiki.repo_cache import BuildOutcome, RepoCachePaths, repo_lock


def _hold_lock(path: str, ready, release) -> None:
    """Child process: hold the lock until told to release."""

    async def _run() -> None:
        async with repo_lock(Path(path), timeout=2.0) as ok:
            if ok:
                ready.set()
                release.wait(10)

    asyncio.run(_run())


def test_models(tmp_path: Path) -> None:
    paths = RepoCachePaths(slug="a", repository="o/r", clone_dir=tmp_path, plane_dir=tmp_path, lock_path=tmp_path / "l")
    assert paths.slug == "a"
    out = BuildOutcome(ok=True, returncode=0, timed_out=False, duration_s=0.1, stderr_tail="")
    assert out.ok


async def test_repo_lock_is_exclusive_across_processes(tmp_path: Path) -> None:
    """Second acquirer gets `False` while the first holds it."""
    lock = tmp_path / "x" / "repo.lock"
    ctx = mp.get_context("spawn")
    ready, release = ctx.Event(), ctx.Event()
    proc = ctx.Process(target=_hold_lock, args=(str(lock), ready, release))
    proc.start()
    try:
        assert await asyncio.to_thread(ready.wait, 20)
        async with repo_lock(lock, timeout=0.2) as ok:
            assert ok is False
        release.set()
        await asyncio.to_thread(proc.join, 10)
        async with repo_lock(lock, timeout=1.0) as ok:
            assert ok is True
    finally:
        release.set()
        proc.join(5)
        if proc.is_alive():
            proc.terminate()


async def test_repo_lock_does_not_block_event_loop(tmp_path: Path) -> None:
    """A contended acquire with timeout still lets other coroutines run."""
    lock = tmp_path / "repo.lock"
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    async with repo_lock(lock, timeout=0.0) as first:
        assert first
        task = asyncio.create_task(ticker())
        start = time.monotonic()
        async with repo_lock(lock, timeout=0.3) as second:
            assert second is False
        assert time.monotonic() - start >= 0.25
        task.cancel()
    assert ticks >= 5


async def test_repo_lock_released_on_exception_and_cancellation(tmp_path: Path) -> None:
    lock = tmp_path / "repo.lock"
    with pytest.raises(RuntimeError):
        async with repo_lock(lock, timeout=0.0):
            raise RuntimeError("boom")
    async with repo_lock(lock, timeout=0.0) as ok:
        assert ok

    async def holder() -> None:
        async with repo_lock(lock, timeout=0.0):
            await asyncio.sleep(30)

    task = asyncio.create_task(holder())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with repo_lock(lock, timeout=0.0) as ok:
        assert ok


async def test_repo_lock_noop_without_fcntl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repo_cache, "fcntl", None)
    lock = tmp_path / "repo.lock"
    async with repo_lock(lock, timeout=0.0) as a:
        async with repo_lock(lock, timeout=0.0) as b:
            assert a is True and b is True
