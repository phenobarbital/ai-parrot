"""Bounded, lifecycle-managed process executor for CPU-bound perception work (FEAT-574)."""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")

_START_METHOD = "spawn"  # never fork a process that runs an event loop and threads


class CpuExecutor:
    """Lazily created, bounded ProcessPoolExecutor; one per PlanogramCompliance run.

    Usage::

        async with CpuExecutor(max_workers=2) as cpu:
            shapes = await cpu.run(propose_shapes, image, profiles)
    """

    def __init__(self, max_workers: int = 2) -> None:
        """Store limits only; no process is started here.

        Args:
            max_workers: Upper bound of worker processes AND of in-flight submissions.

        Raises:
            ValueError: ``max_workers`` < 1.
        """
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self.max_workers = max_workers
        self.logger = logging.getLogger(__name__)
        self._pool: Optional[ProcessPoolExecutor] = None
        self._slots: Optional[asyncio.Semaphore] = None
        self._closed = False

    def _ensure_pool(self) -> ProcessPoolExecutor:
        """Create the pool on first use (spawn context).

        Returns:
            The process pool.
        """
        if self._pool is None:
            self.logger.debug("starting process pool: %d workers (%s)", self.max_workers, _START_METHOD)
            self._pool = ProcessPoolExecutor(
                max_workers=self.max_workers, mp_context=multiprocessing.get_context(_START_METHOD)
            )
        return self._pool

    def _discard_pool(self) -> None:
        """Shut the current pool down without waiting and forget it."""
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    async def run(self, fn: Callable[..., T], *args: Any) -> T:
        """Run ``fn(*args)`` in a worker process and await its result.

        ``fn`` must be module-level and picklable. Cancellation-safe: cancelling the awaiting
        coroutine releases its slot and leaves the executor usable.

        Args:
            fn: Module-level, picklable callable.
            *args: Positional arguments (picklable).

        Returns:
            ``fn(*args)``.

        Raises:
            RuntimeError: The executor was closed.
            BrokenProcessPool: A worker died; the pool is discarded and rebuilt on the next call.
        """
        if self._closed:
            raise RuntimeError("CpuExecutor is closed")
        if self._slots is None:
            self._slots = asyncio.Semaphore(self.max_workers)
        async with self._slots:
            if self._closed:
                raise RuntimeError("CpuExecutor is closed")
            loop = asyncio.get_running_loop()
            try:
                return await loop.run_in_executor(self._ensure_pool(), fn, *args)
            except BrokenProcessPool:
                self.logger.error("process pool broken (a worker died); it will be rebuilt on the next run")
                self._discard_pool()
                raise

    async def aclose(self) -> None:
        """Release the pool. Idempotent, non-blocking; queued work is cancelled."""
        self._closed = True
        self._discard_pool()

    async def __aenter__(self) -> "CpuExecutor":
        """Return the executor itself."""
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Close the executor on exit (also on exception)."""
        await self.aclose()
