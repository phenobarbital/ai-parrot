"""Client for submitting tasks to AgentService via Redis Streams."""
import asyncio
import json
import uuid
from typing import Optional

import redis.asyncio as aioredis
from navconfig.logging import logging

from .models import AgentTask, TaskResult


class AgentServiceClient:
    """Async client for submitting tasks to a running AgentService.

    Publishes tasks to a Redis Stream and optionally waits for results
    on the response stream.

    Usage::

        async with AgentServiceClient("redis://localhost:6379") as client:
            task_id = await client.submit_task(
                AgentTask(agent_name="MyAgent", prompt="Hello")
            )
            result = await client.get_result(task_id, timeout=30)
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        redis_db: int = 0,
        task_stream: str = "parrot:agent_tasks",
        result_stream: str = "parrot:agent_results",
    ):
        self.redis_url = redis_url
        self.redis_db = redis_db
        self.task_stream = task_stream
        self.result_stream = result_stream
        self._redis: Optional[aioredis.Redis] = None
        self.logger = logging.getLogger("parrot.services.client")

    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = await aioredis.from_url(
            self.redis_url, db=self.redis_db, decode_responses=True
        )

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def submit_task(self, task: AgentTask) -> str:
        """Publish a task to the AgentService task stream.

        Args:
            task: The agent task to submit.

        Returns:
            The task ID.
        """
        if not self._redis:
            raise RuntimeError("Not connected. Call connect() first.")

        payload = task.model_dump_json()
        await self._redis.xadd(
            self.task_stream,
            {
                "task_id": task.task_id,
                "agent_name": task.agent_name,
                "payload": payload,
            },
        )
        self.logger.info(
            f"Submitted task {task.task_id} → '{task.agent_name}' "
            f"to stream '{self.task_stream}'"
        )
        return task.task_id

    async def get_result(
        self, task_id: str, timeout: float = 60.0
    ) -> Optional[TaskResult]:
        """Wait for a task result on the response stream.

        Polls the result stream for a matching task_id. This is a
        simple polling implementation suitable for occasional use.

        Args:
            task_id: Task ID to wait for.
            timeout: Maximum seconds to wait.

        Returns:
            TaskResult if found within timeout, None otherwise.
        """
        if not self._redis:
            raise RuntimeError("Not connected. Call connect() first.")

        deadline = asyncio.get_event_loop().time() + timeout
        last_id = "0-0"

        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            block_ms = min(int(remaining * 1000), 2000)
            if block_ms <= 0:
                break

            messages = await self._redis.xread(
                {self.result_stream: last_id},
                count=10,
                block=block_ms,
            )

            if not messages:
                continue

            for _stream, entries in messages:
                for msg_id, data in entries:
                    last_id = msg_id
                    if data.get("task_id") == task_id:
                        payload = data.get("payload", "{}")
                        return TaskResult.model_validate_json(payload)

        self.logger.warning(
            f"Timeout waiting for result of task {task_id}"
        )
        return None

    async def submit_and_wait(
        self, task: AgentTask, timeout: float = 60.0
    ) -> Optional[TaskResult]:
        """Submit a task and wait for its result.

        Convenience method combining ``submit_task`` and ``get_result``.

        Args:
            task: The agent task to submit.
            timeout: Maximum seconds to wait for result.

        Returns:
            TaskResult if completed within timeout.
        """
        task_id = await self.submit_task(task)
        return await self.get_result(task_id, timeout=timeout)
