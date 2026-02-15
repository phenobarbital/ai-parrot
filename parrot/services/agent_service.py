"""AgentService — standalone asyncio runtime for autonomous AI agents."""
import asyncio
import time
from typing import Any, Optional, TYPE_CHECKING

import redis.asyncio as aioredis
from navconfig.logging import logging

from .delivery import DeliveryRouter
from .heartbeat import HeartbeatScheduler
from .models import (
    AgentServiceConfig,
    AgentTask,
    DeliveryChannel,
    TaskResult,
    TaskStatus,
)
from .redis_listener import RedisTaskListener
from .task_queue import TaskQueue
from .worker_pool import WorkerPool

if TYPE_CHECKING:
    from ..bots.abstract import AbstractBot
    from ..manager import BotManager


class AgentService:
    """Standalone asyncio runtime for autonomous AI agents.

    Composes:
    - ``TaskQueue`` for priority-aware task management
    - ``WorkerPool`` for bounded concurrent execution
    - ``HeartbeatScheduler`` for periodic agent wake-ups
    - ``RedisTaskListener`` for IPC with the web server
    - ``DeliveryRouter`` for routing results to delivery channels

    Agent resolution uses ``BotManager.get_bot()`` — the same mechanism
    used by ``TelegramBotManager`` and ``AutonomousOrchestrator``.

    Usage::

        from parrot.services import AgentService, AgentServiceConfig

        config = AgentServiceConfig(redis_url="redis://localhost:6379")
        service = AgentService(config, bot_manager)
        await service.start()
        # ... runs until stop() is called
        await service.stop()
    """

    def __init__(
        self,
        config: AgentServiceConfig,
        bot_manager: "BotManager",
    ):
        self.config = config
        self.bot_manager = bot_manager
        self.logger = logging.getLogger("parrot.services.agent_service")

        # Core components (initialized in start())
        self._redis: Optional[aioredis.Redis] = None
        self._task_queue: Optional[TaskQueue] = None
        self._worker_pool: Optional[WorkerPool] = None
        self._heartbeat: Optional[HeartbeatScheduler] = None
        self._listener: Optional[RedisTaskListener] = None
        self._delivery: Optional[DeliveryRouter] = None

        # Runtime state
        self._running = False
        self._consumer_task: Optional[asyncio.Task] = None
        self._listener_task: Optional[asyncio.Task] = None

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Initialize all components and begin processing."""
        self.logger.info("Starting AgentService...")

        # 1. Connect Redis
        self._redis = await aioredis.from_url(
            self.config.redis_url,
            db=self.config.redis_db,
            decode_responses=True,
        )
        self.logger.info(f"Connected to Redis: {self.config.redis_url}")

        # 2. Task queue with Redis persistence
        self._task_queue = TaskQueue(redis=self._redis)
        recovered = await self._task_queue.recover()
        if recovered:
            self.logger.info(f"Recovered {recovered} task(s) from Redis")

        # 3. Worker pool
        self._worker_pool = WorkerPool(max_workers=self.config.max_workers)
        self.logger.info(
            f"Worker pool ready (max_workers={self.config.max_workers})"
        )

        # 4. Delivery router
        self._delivery = DeliveryRouter()

        # 5. Heartbeat scheduler
        self._heartbeat = HeartbeatScheduler(
            task_callback=self.submit_task,
        )
        for hb_config in self.config.heartbeats:
            self._heartbeat.register(hb_config)
        self._heartbeat.start()

        # 6. Redis Streams listener
        self._listener = RedisTaskListener(
            redis_url=self.config.redis_url,
            redis_db=self.config.redis_db,
            task_stream=self.config.task_stream,
            result_stream=self.config.result_stream,
            consumer_group=self.config.consumer_group,
            consumer_name=self.config.consumer_name,
        )
        await self._listener.connect()

        # 7. Start background loops
        self._running = True
        self._consumer_task = asyncio.create_task(
            self._run_consumer_loop(), name="agent_service_consumer"
        )
        self._listener_task = asyncio.create_task(
            self._run_listener_loop(), name="agent_service_listener"
        )

        self.logger.info(
            "✅ AgentService started "
            f"(workers={self.config.max_workers}, "
            f"heartbeats={self._heartbeat.registered_count}, "
            f"stream={self.config.task_stream})"
        )

    async def stop(self) -> None:
        """Graceful shutdown of all components."""
        self.logger.info("Stopping AgentService...")
        self._running = False

        # Stop heartbeat scheduler
        if self._heartbeat:
            self._heartbeat.stop()

        # Stop Redis listener
        if self._listener:
            self._listener.stop()
            await self._listener.disconnect()

        # Cancel background loops
        for task in [self._consumer_task, self._listener_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

        # Drain worker pool
        if self._worker_pool:
            await self._worker_pool.shutdown(
                timeout=self.config.shutdown_timeout_seconds
            )

        # Close delivery router
        if self._delivery:
            await self._delivery.close()

        # Close Redis
        if self._redis:
            await self._redis.close()

        self.logger.info("AgentService stopped")

    # =========================================================================
    # Public API
    # =========================================================================

    async def submit_task(self, task: AgentTask) -> str:
        """Submit a task for execution.

        Args:
            task: The agent task to execute.

        Returns:
            The task ID.
        """
        if not self._running:
            raise RuntimeError("AgentService is not running")

        task.status = TaskStatus.QUEUED
        await self._task_queue.put(task)
        self.logger.info(
            f"Task submitted: {task.task_id} → '{task.agent_name}' "
            f"(priority={task.priority})"
        )
        return task.task_id

    # =========================================================================
    # Internal: Consumer Loop
    # =========================================================================

    async def _run_consumer_loop(self) -> None:
        """Main loop: dequeue tasks and submit to worker pool."""
        self.logger.debug("Consumer loop started")
        while self._running:
            try:
                # Block until a task is available
                task = await asyncio.wait_for(
                    self._task_queue.get(), timeout=1.0
                )
                await self._worker_pool.submit(
                    self._process_task(task),
                    name=f"task_{task.task_id[:8]}",
                )
                self._task_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error(f"Consumer loop error: {exc}", exc_info=True)
                await asyncio.sleep(0.5)

    async def _run_listener_loop(self) -> None:
        """Listen for tasks from Redis Streams and enqueue them."""
        self.logger.debug("Listener loop started")
        try:
            async for task in self._listener.listen():
                if not self._running:
                    break
                await self.submit_task(task)
                # ACK after enqueuing
                msg_id = task.metadata.get("_stream_message_id")
                if msg_id:
                    await self._listener.ack(msg_id)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.logger.error(f"Listener loop error: {exc}", exc_info=True)

    # =========================================================================
    # Internal: Task Processing
    # =========================================================================

    async def _process_task(self, task: AgentTask) -> TaskResult:
        """Execute an agent task and deliver the result."""
        start = time.monotonic()
        task.status = TaskStatus.RUNNING
        self.logger.info(
            f"Processing task {task.task_id} → '{task.agent_name}'"
        )

        try:
            # Resolve agent
            agent = await self._resolve_agent(task.agent_name)
            if not agent:
                raise ValueError(
                    f"Agent '{task.agent_name}' not found in BotManager"
                )

            # Execute
            response = await self._execute_agent(agent, task)

            # Build result
            elapsed = (time.monotonic() - start) * 1000
            output_text = self._extract_output(response)

            result = TaskResult(
                task_id=task.task_id,
                agent_name=task.agent_name,
                success=True,
                output=output_text,
                execution_time_ms=elapsed,
                metadata=task.metadata,
            )

        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            self.logger.error(
                f"Task {task.task_id} failed: {exc}", exc_info=True
            )
            result = TaskResult(
                task_id=task.task_id,
                agent_name=task.agent_name,
                success=False,
                error=str(exc),
                execution_time_ms=elapsed,
            )

        # Update task status
        task.status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED

        # Deliver result
        await self._deliver_result(task, result)

        # Remove from Redis persistence
        if self._task_queue:
            await self._task_queue._remove_persisted(task)

        return result

    async def _resolve_agent(self, agent_name: str) -> Optional["AbstractBot"]:
        """Resolve agent instance via BotManager."""
        try:
            return await self.bot_manager.get_bot(agent_name)
        except Exception as exc:
            self.logger.error(f"Failed to resolve agent '{agent_name}': {exc}")
            return None

    async def _execute_agent(
        self, agent: "AbstractBot", task: AgentTask
    ) -> Any:
        """Execute the agent's ask() method with optional timeout."""
        kwargs: dict[str, Any] = {}
        if task.user_id:
            kwargs["user_id"] = task.user_id
        if task.session_id:
            kwargs["session_id"] = task.session_id

        # Use specific method if requested
        if task.method_name and hasattr(agent, task.method_name):
            method = getattr(agent, task.method_name)
            return await asyncio.wait_for(
                method(task.prompt, **kwargs),
                timeout=self.config.task_timeout_seconds,
            )

        return await asyncio.wait_for(
            agent.ask(task.prompt, **kwargs),
            timeout=self.config.task_timeout_seconds,
        )

    def _extract_output(self, response: Any) -> str:
        """Extract text output from an AIMessage or similar response."""
        if isinstance(response, str):
            return response

        # AIMessage.to_text property
        if hasattr(response, "to_text"):
            return response.to_text

        if hasattr(response, "output"):
            return str(response.output)

        if hasattr(response, "response") and response.response:
            return response.response

        return str(response)

    async def _deliver_result(
        self, task: AgentTask, result: TaskResult
    ) -> None:
        """Route the result through delivery and Redis Streams."""
        # Deliver via configured channel
        if self._delivery:
            await self._delivery.deliver(task, result)

        # Always publish to Redis response stream for IPC
        if (self._listener
                and getattr(self._listener, '_connected', False)
                and task.delivery.channel != DeliveryChannel.REDIS_STREAM):
            try:
                await self._listener.publish_result(result)
            except Exception as exc:
                self.logger.warning(
                    f"Failed to publish result to stream: {exc}"
                )

    # =========================================================================
    # Status / Monitoring
    # =========================================================================

    def get_status(self) -> dict:
        """Return service status for monitoring."""
        return {
            "running": self._running,
            "queue_size": self._task_queue.qsize if self._task_queue else 0,
            "active_workers": (
                self._worker_pool.active_count if self._worker_pool else 0
            ),
            "available_slots": (
                self._worker_pool.available_slots if self._worker_pool else 0
            ),
            "heartbeats": (
                self._heartbeat.registered_count if self._heartbeat else 0
            ),
        }
