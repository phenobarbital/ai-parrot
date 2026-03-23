"""Bounded async worker pool for concurrent agent execution."""
import asyncio
from typing import Any, Coroutine, Optional

from navconfig.logging import logging


class WorkerPool:
    """Limits concurrent agent executions using an asyncio semaphore."""

    def __init__(self, max_workers: int = 10):
        self._semaphore = asyncio.Semaphore(max_workers)
        self._max_workers = max_workers
        self._active_tasks: set[asyncio.Task] = set()
        self._shutting_down = False
        self.logger = logging.getLogger("parrot.services.worker_pool")

    @property
    def active_count(self) -> int:
        """Number of currently executing tasks."""
        return len(self._active_tasks)

    @property
    def available_slots(self) -> int:
        """Number of available worker slots."""
        return self._max_workers - self.active_count

    async def submit(self, coro: Coroutine[Any, Any, Any], name: Optional[str] = None) -> asyncio.Task:
        """Submit a coroutine for execution within the bounded pool.

        Args:
            coro: Coroutine to execute.
            name: Optional task name for debugging.

        Returns:
            The created asyncio.Task.
        """
        if self._shutting_down:
            raise RuntimeError("WorkerPool is shutting down, cannot accept new tasks")

        task = asyncio.create_task(self._run(coro), name=name)
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)
        return task

    async def _run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Acquire semaphore, run coroutine, release."""
        async with self._semaphore:
            return await coro

    async def shutdown(self, timeout: float = 30.0) -> None:
        """Gracefully shut down the worker pool.

        Waits for active tasks up to ``timeout`` seconds, then cancels remaining.
        """
        self._shutting_down = True
        if not self._active_tasks:
            return

        self.logger.info(
            f"Shutting down worker pool: {len(self._active_tasks)} active tasks"
        )

        # Wait for active tasks with timeout
        done, pending = await asyncio.wait(
            self._active_tasks, timeout=timeout, return_when=asyncio.ALL_COMPLETED
        )

        # Cancel any tasks that didn't finish
        for task in pending:
            task.cancel()
            self.logger.warning(f"Cancelled task: {task.get_name()}")

        # Wait briefly for cancellation to propagate
        if pending:
            await asyncio.wait(pending, timeout=2.0)

        self._active_tasks.clear()
        self.logger.info("Worker pool shutdown complete")
