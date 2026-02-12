"""Priority task queue with optional Redis persistence."""
import asyncio
import json
import time
from typing import Optional

from navconfig.logging import logging

from .models import AgentTask


class TaskQueue:
    """Priority-aware async task queue.

    Uses ``asyncio.PriorityQueue`` for in-memory hot path with optional
    Redis sorted-set persistence for crash recovery.
    """

    # Redis key for the persistent sorted set
    REDIS_KEY = "parrot:task_queue"

    def __init__(self, maxsize: int = 0, redis: Optional[object] = None):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=maxsize)
        self._redis = redis
        self._counter = 0  # Tie-breaker for same-priority FIFO
        self.logger = logging.getLogger("parrot.services.task_queue")

    async def put(self, task: AgentTask) -> None:
        """Enqueue a task with priority ordering.

        Lower priority value = higher priority. Tasks with equal priority
        maintain FIFO order via a monotonic counter.
        """
        self._counter += 1
        score = (task.priority, self._counter)
        await self._queue.put((score, task))
        self.logger.debug(
            f"Enqueued task {task.task_id} for '{task.agent_name}' "
            f"(priority={task.priority})"
        )

        # Persist if Redis is available
        if self._redis:
            await self._persist_task(task)

    async def get(self) -> AgentTask:
        """Dequeue the highest-priority task (blocking)."""
        _score, task = await self._queue.get()
        return task

    def get_nowait(self) -> Optional[AgentTask]:
        """Non-blocking dequeue, returns None if empty."""
        try:
            _score, task = self._queue.get_nowait()
            return task
        except asyncio.QueueEmpty:
            return None

    @property
    def qsize(self) -> int:
        """Current number of tasks in the queue."""
        return self._queue.qsize()

    @property
    def empty(self) -> bool:
        """True if queue has no pending tasks."""
        return self._queue.empty()

    async def _persist_task(self, task: AgentTask) -> None:
        """Persist a task to Redis sorted set."""
        try:
            score = task.priority * 1e10 + time.time()
            payload = task.model_dump_json()
            await self._redis.zadd(self.REDIS_KEY, {payload: score})
        except Exception as exc:
            self.logger.warning(f"Failed to persist task {task.task_id}: {exc}")

    async def _remove_persisted(self, task: AgentTask) -> None:
        """Remove a completed task from Redis."""
        if not self._redis:
            return
        try:
            payload = task.model_dump_json()
            await self._redis.zrem(self.REDIS_KEY, payload)
        except Exception as exc:
            self.logger.warning(f"Failed to remove persisted task {task.task_id}: {exc}")

    async def recover(self) -> int:
        """Recover tasks from Redis on startup.

        Returns:
            Number of tasks recovered.
        """
        if not self._redis:
            return 0

        try:
            raw_items = await self._redis.zrangebyscore(
                self.REDIS_KEY, "-inf", "+inf"
            )
            count = 0
            for raw in raw_items:
                try:
                    task = AgentTask.model_validate_json(raw)
                    await self.put(task)
                    count += 1
                except Exception as exc:
                    self.logger.warning(f"Failed to recover task: {exc}")

            if count:
                self.logger.info(f"Recovered {count} task(s) from Redis")
            return count
        except Exception as exc:
            self.logger.error(f"Failed to recover tasks from Redis: {exc}")
            return 0

    async def clear_persisted(self) -> None:
        """Remove all persisted tasks from Redis."""
        if not self._redis:
            return
        try:
            await self._redis.delete(self.REDIS_KEY)
        except Exception as exc:
            self.logger.warning(f"Failed to clear persisted tasks: {exc}")

    def task_done(self) -> None:
        """Mark the last dequeued task as done."""
        self._queue.task_done()
