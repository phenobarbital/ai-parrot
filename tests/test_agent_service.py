"""Tests for parrot.services — AgentService components."""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.services.models import (
    AgentServiceConfig,
    AgentTask,
    DeliveryChannel,
    DeliveryConfig,
    HeartbeatConfig,
    TaskPriority,
    TaskResult,
    TaskStatus,
)
from parrot.services.task_queue import TaskQueue
from parrot.services.worker_pool import WorkerPool


# =========================================================================
# Models
# =========================================================================


class TestAgentTask:
    """Tests for AgentTask Pydantic model."""

    def test_defaults(self):
        task = AgentTask(agent_name="TestBot", prompt="Hello")
        assert task.agent_name == "TestBot"
        assert task.prompt == "Hello"
        assert task.priority == TaskPriority.NORMAL
        assert task.status == TaskStatus.PENDING
        assert task.task_id  # auto-generated
        assert task.delivery.channel == DeliveryChannel.LOG

    def test_custom_priority(self):
        task = AgentTask(
            agent_name="Bot",
            prompt="test",
            priority=TaskPriority.CRITICAL,
        )
        assert task.priority == 1

    def test_serialization_roundtrip(self):
        task = AgentTask(
            agent_name="Bot",
            prompt="Round trip test",
            delivery=DeliveryConfig(
                channel=DeliveryChannel.WEBHOOK,
                webhook_url="https://example.com/hook",
            ),
            metadata={"key": "value"},
        )
        json_str = task.model_dump_json()
        restored = AgentTask.model_validate_json(json_str)
        assert restored.agent_name == task.agent_name
        assert restored.delivery.webhook_url == "https://example.com/hook"
        assert restored.metadata["key"] == "value"

    def test_invalid_priority_rejected(self):
        with pytest.raises(Exception):
            AgentTask(agent_name="Bot", prompt="test", priority=0)

        with pytest.raises(Exception):
            AgentTask(agent_name="Bot", prompt="test", priority=11)


class TestTaskResult:
    """Tests for TaskResult Pydantic model."""

    def test_success_result(self):
        result = TaskResult(
            task_id="abc123",
            agent_name="TestBot",
            success=True,
            output="Hello world",
            execution_time_ms=150.5,
        )
        assert result.success is True
        assert result.output == "Hello world"
        assert result.error is None

    def test_failure_result(self):
        result = TaskResult(
            task_id="abc123",
            agent_name="TestBot",
            success=False,
            error="Agent not found",
        )
        assert result.success is False
        assert result.error == "Agent not found"


class TestDeliveryChannel:
    """Tests for DeliveryChannel enum."""

    def test_all_channels_exist(self):
        expected = {"webhook", "telegram", "teams", "email", "log", "redis_stream"}
        actual = {c.value for c in DeliveryChannel}
        assert actual == expected


class TestAgentServiceConfig:
    """Tests for AgentServiceConfig."""

    def test_defaults(self):
        config = AgentServiceConfig()
        assert config.redis_url == "redis://localhost:6379"
        assert config.max_workers == 10
        assert config.task_stream == "parrot:agent_tasks"
        assert config.result_stream == "parrot:agent_results"
        assert config.heartbeats == []


# =========================================================================
# Task Queue
# =========================================================================


class TestTaskQueue:
    """Tests for in-memory TaskQueue."""

    @pytest.mark.asyncio
    async def test_priority_ordering(self):
        queue = TaskQueue()
        low = AgentTask(agent_name="A", prompt="low", priority=TaskPriority.LOW)
        high = AgentTask(agent_name="A", prompt="high", priority=TaskPriority.HIGH)
        normal = AgentTask(agent_name="A", prompt="normal", priority=TaskPriority.NORMAL)

        await queue.put(low)
        await queue.put(high)
        await queue.put(normal)

        first = await queue.get()
        second = await queue.get()
        third = await queue.get()

        assert first.prompt == "high"
        assert second.prompt == "normal"
        assert third.prompt == "low"

    @pytest.mark.asyncio
    async def test_fifo_same_priority(self):
        queue = TaskQueue()
        t1 = AgentTask(agent_name="A", prompt="first", priority=5)
        t2 = AgentTask(agent_name="A", prompt="second", priority=5)
        t3 = AgentTask(agent_name="A", prompt="third", priority=5)

        await queue.put(t1)
        await queue.put(t2)
        await queue.put(t3)

        assert (await queue.get()).prompt == "first"
        assert (await queue.get()).prompt == "second"
        assert (await queue.get()).prompt == "third"

    @pytest.mark.asyncio
    async def test_qsize_and_empty(self):
        queue = TaskQueue()
        assert queue.empty is True
        assert queue.qsize == 0

        await queue.put(AgentTask(agent_name="A", prompt="test"))
        assert queue.empty is False
        assert queue.qsize == 1

    @pytest.mark.asyncio
    async def test_get_nowait_empty(self):
        queue = TaskQueue()
        result = queue.get_nowait()
        assert result is None


# =========================================================================
# Worker Pool
# =========================================================================


class TestWorkerPool:
    """Tests for WorkerPool."""

    @pytest.mark.asyncio
    async def test_concurrency_limit(self):
        max_concurrent = 0
        current = 0
        lock = asyncio.Lock()

        async def tracked_task():
            nonlocal max_concurrent, current
            async with lock:
                current += 1
                max_concurrent = max(max_concurrent, current)
            await asyncio.sleep(0.05)
            async with lock:
                current -= 1

        pool = WorkerPool(max_workers=3)
        tasks = [await pool.submit(tracked_task()) for _ in range(10)]
        await asyncio.gather(*tasks)

        assert max_concurrent <= 3

    @pytest.mark.asyncio
    async def test_shutdown_cancels_pending(self):
        async def slow_task():
            await asyncio.sleep(10)

        pool = WorkerPool(max_workers=1)
        await pool.submit(slow_task(), name="slow1")
        await pool.submit(slow_task(), name="slow2")

        await pool.shutdown(timeout=0.5)
        assert pool.active_count == 0

    @pytest.mark.asyncio
    async def test_reject_after_shutdown(self):
        pool = WorkerPool(max_workers=2)
        await pool.shutdown()

        coro = asyncio.sleep(0)
        with pytest.raises(RuntimeError, match="shutting down"):
            await pool.submit(coro)
        coro.close()  # Prevent unawaited coroutine warning

    @pytest.mark.asyncio
    async def test_available_slots(self):
        pool = WorkerPool(max_workers=5)
        assert pool.available_slots == 5
        assert pool.active_count == 0


# =========================================================================
# Heartbeat Scheduler
# =========================================================================


class TestHeartbeatScheduler:
    """Tests for HeartbeatScheduler."""

    def test_register_cron(self):
        from parrot.services.heartbeat import HeartbeatScheduler

        callback = AsyncMock()
        scheduler = HeartbeatScheduler(task_callback=callback)

        config = HeartbeatConfig(
            agent_name="TestBot",
            cron_expression="*/5 * * * *",
        )
        job_id = scheduler.register(config)
        assert job_id == "heartbeat_TestBot"
        assert scheduler.registered_count == 1

    def test_register_interval(self):
        from parrot.services.heartbeat import HeartbeatScheduler

        callback = AsyncMock()
        scheduler = HeartbeatScheduler(task_callback=callback)

        config = HeartbeatConfig(
            agent_name="IntervalBot",
            interval_seconds=60,
        )
        job_id = scheduler.register(config)
        assert job_id == "heartbeat_IntervalBot"

    def test_register_disabled(self):
        from parrot.services.heartbeat import HeartbeatScheduler

        callback = AsyncMock()
        scheduler = HeartbeatScheduler(task_callback=callback)

        config = HeartbeatConfig(
            agent_name="DisabledBot",
            interval_seconds=60,
            enabled=False,
        )
        result = scheduler.register(config)
        assert result is None
        assert scheduler.registered_count == 0

    def test_register_no_trigger(self):
        from parrot.services.heartbeat import HeartbeatScheduler

        callback = AsyncMock()
        scheduler = HeartbeatScheduler(task_callback=callback)

        config = HeartbeatConfig(agent_name="NoTrigger")
        result = scheduler.register(config)
        assert result is None


# =========================================================================
# Delivery Router
# =========================================================================


class TestDeliveryRouter:
    """Tests for DeliveryRouter."""

    @pytest.mark.asyncio
    async def test_deliver_log(self):
        from parrot.services.delivery import DeliveryRouter

        router = DeliveryRouter()
        task = AgentTask(
            agent_name="Bot",
            prompt="test",
            delivery=DeliveryConfig(channel=DeliveryChannel.LOG),
        )
        result = TaskResult(
            task_id=task.task_id,
            agent_name="Bot",
            success=True,
            output="All good",
        )

        ok = await router.deliver(task, result)
        assert ok is True
        await router.close()

    @pytest.mark.asyncio
    async def test_deliver_webhook(self):
        from parrot.services.delivery import DeliveryRouter

        router = DeliveryRouter()
        task = AgentTask(
            agent_name="Bot",
            prompt="test",
            delivery=DeliveryConfig(
                channel=DeliveryChannel.WEBHOOK,
                webhook_url="https://httpbin.org/post",
            ),
        )
        result = TaskResult(
            task_id=task.task_id,
            agent_name="Bot",
            success=True,
            output="Result",
        )

        # Mock aiohttp to avoid real HTTP call
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.closed = False

        router._http_session = mock_session

        ok = await router.deliver(task, result)
        assert ok is True
        mock_session.post.assert_called_once()
        await router.close()


# =========================================================================
# AgentService Lifecycle (Mocked)
# =========================================================================


class TestAgentServiceLifecycle:
    """Test AgentService start/stop with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_lifecycle(self):
        from parrot.services.agent_service import AgentService

        config = AgentServiceConfig(redis_url="redis://localhost:6379")
        bot_manager = MagicMock()

        # Mock Redis connection
        mock_redis = AsyncMock()
        mock_redis.close = AsyncMock()
        mock_redis.xgroup_create = AsyncMock()
        mock_redis.xreadgroup = AsyncMock(return_value=[])
        mock_redis.zrangebyscore = AsyncMock(return_value=[])

        with patch("parrot.services.agent_service.aioredis") as mock_aioredis, \
             patch("parrot.services.redis_listener.aioredis") as mock_listener_redis:
            mock_aioredis.from_url = AsyncMock(return_value=mock_redis)
            mock_listener_redis.from_url = AsyncMock(return_value=mock_redis)
            mock_listener_redis.ResponseError = Exception

            service = AgentService(config, bot_manager)
            await service.start()

            assert service._running is True
            status = service.get_status()
            assert status["running"] is True
            assert status["queue_size"] == 0

            await service.stop()
            assert service._running is False


# =========================================================================
# Client
# =========================================================================


class TestAgentServiceClient:
    """Tests for AgentServiceClient."""

    @pytest.mark.asyncio
    async def test_submit_task(self):
        from parrot.services.client import AgentServiceClient

        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1-0")
        mock_redis.close = AsyncMock()

        client = AgentServiceClient()
        client._redis = mock_redis

        task = AgentTask(agent_name="TestBot", prompt="Hello")
        task_id = await client.submit_task(task)

        assert task_id == task.task_id
        mock_redis.xadd.assert_called_once()
        await client.disconnect()
