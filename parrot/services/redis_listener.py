"""Redis Streams listener for IPC with the web server."""
import asyncio
import json
from typing import AsyncIterator, Optional

import redis.asyncio as aioredis
from navconfig.logging import logging

from .models import AgentTask, DeliveryChannel, DeliveryConfig, TaskResult


class RedisTaskListener:
    """Listens for incoming tasks on a Redis Stream using consumer groups.

    Uses ``XREADGROUP`` for reliable delivery and ``XACK`` for acknowledgement.
    Also publishes results back on a response stream.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        redis_db: int = 0,
        task_stream: str = "parrot:agent_tasks",
        result_stream: str = "parrot:agent_results",
        consumer_group: str = "agent_service",
        consumer_name: Optional[str] = None,
    ):
        self.redis_url = redis_url
        self.redis_db = redis_db
        self.task_stream = task_stream
        self.result_stream = result_stream
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name or f"worker_{id(self)}"
        self._redis: Optional[aioredis.Redis] = None
        self._running = False
        self.logger = logging.getLogger("parrot.services.redis_listener")

    async def connect(self) -> None:
        """Connect to Redis and ensure consumer group exists."""
        self._redis = await aioredis.from_url(
            self.redis_url, db=self.redis_db, decode_responses=True
        )
        # Create consumer group (ignore if already exists)
        try:
            await self._redis.xgroup_create(
                self.task_stream,
                self.consumer_group,
                id="0",
                mkstream=True,
            )
            self.logger.info(
                f"Created consumer group '{self.consumer_group}' on "
                f"stream '{self.task_stream}'"
            )
        except aioredis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                self.logger.debug(
                    f"Consumer group '{self.consumer_group}' already exists"
                )
            else:
                raise

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        self._running = False
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def listen(self) -> AsyncIterator[AgentTask]:
        """Yield AgentTask instances from the Redis Stream.

        Uses ``XREADGROUP`` with blocking reads. Call ``ack()`` after
        processing each task.
        """
        if not self._redis:
            raise RuntimeError("Not connected. Call connect() first.")

        self._running = True
        self.logger.info(
            f"Listening on stream '{self.task_stream}' "
            f"(group={self.consumer_group}, consumer={self.consumer_name})"
        )

        while self._running:
            try:
                messages = await self._redis.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    streams={self.task_stream: ">"},
                    count=1,
                    block=1000,  # Block for 1 second then retry
                )

                if not messages:
                    continue

                for _stream, entries in messages:
                    for message_id, data in entries:
                        try:
                            task = self._parse_task(message_id, data)
                            yield task
                        except Exception as exc:
                            self.logger.error(
                                f"Failed to parse task from message "
                                f"{message_id}: {exc}"
                            )
                            # ACK malformed messages to avoid redelivery
                            await self.ack(message_id)

            except asyncio.CancelledError:
                self.logger.info("Listen loop cancelled")
                break
            except aioredis.ConnectionError as exc:
                self.logger.error(f"Redis connection lost: {exc}")
                await asyncio.sleep(2.0)
            except Exception as exc:
                self.logger.error(f"Unexpected error in listen loop: {exc}")
                await asyncio.sleep(1.0)

    def _parse_task(self, message_id: str, data: dict) -> AgentTask:
        """Parse a Redis Stream message into an AgentTask."""
        # Support both JSON-encoded and flat field formats
        if "payload" in data:
            task_data = json.loads(data["payload"])
        else:
            task_data = dict(data)

        # Inject the stream message ID for acknowledgement
        task_data.setdefault("metadata", {})
        task_data["metadata"]["_stream_message_id"] = message_id

        # Ensure delivery config is parsed
        if "delivery" in task_data and isinstance(task_data["delivery"], str):
            task_data["delivery"] = json.loads(task_data["delivery"])

        return AgentTask.model_validate(task_data)

    async def ack(self, message_id: str) -> None:
        """Acknowledge a processed message."""
        if self._redis:
            await self._redis.xack(
                self.task_stream, self.consumer_group, message_id
            )

    async def publish_result(self, result: TaskResult) -> str:
        """Publish a task result to the response stream.

        Returns:
            The stream message ID.
        """
        if not self._redis:
            raise RuntimeError("Not connected. Call connect() first.")

        payload = result.model_dump_json()
        msg_id = await self._redis.xadd(
            self.result_stream,
            {"task_id": result.task_id, "payload": payload},
        )
        self.logger.debug(
            f"Published result for task {result.task_id} → {msg_id}"
        )
        return msg_id

    def stop(self) -> None:
        """Signal the listener to stop."""
        self._running = False
