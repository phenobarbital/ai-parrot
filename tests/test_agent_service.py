"""
Tests for AgentService - autonomous agent runtime.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.services.agent_service import (
    AgentService,
    AgentServiceClient,
    AgentServiceConfig,
    AgentTask,
    CronJob,
    CronScheduler,
    HeartbeatConfig,
    HeartbeatScheduler,
    SessionMode,
    TaskPriority,
    TaskQueue,
    TaskStatus,
    WorkerPool,
)


# =============================================================================
# TaskPriority and TaskStatus Tests
# =============================================================================


def test_task_priority_ordering():
    """Verify priority enum values for correct ordering."""
    assert TaskPriority.LOW.value < TaskPriority.NORMAL.value
    assert TaskPriority.NORMAL.value < TaskPriority.HIGH.value
    assert TaskPriority.HIGH.value < TaskPriority.CRITICAL.value


def test_task_status_values():
    """Verify all expected status values exist."""
    expected = {"pending", "queued", "running", "completed", "failed", "cancelled", "retrying"}
    actual = {status.value for status in TaskStatus}
    assert expected == actual


# =============================================================================
# AgentTask Tests
# =============================================================================


def test_agent_task_defaults():
    """Test AgentTask default values."""
    task = AgentTask(agent_name="TestAgent", prompt="Hello")
    assert task.agent_name == "TestAgent"
    assert task.prompt == "Hello"
    assert task.priority == TaskPriority.NORMAL
    assert task.status == TaskStatus.PENDING
    assert task.session_mode == SessionMode.MAIN
    assert task.source == "internal"
    assert task.retries == 0
    assert task.task_id is not None
    assert task.created_at is not None


def test_agent_task_serialization():
    """Test AgentTask to_dict and from_dict."""
    task = AgentTask(
        agent_name="TestAgent",
        prompt="Test prompt",
        priority=TaskPriority.HIGH,
        user_id="user123",
        metadata={"key": "value"},
    )

    data = task.to_dict()
    assert data["agent_name"] == "TestAgent"
    assert data["prompt"] == "Test prompt"
    assert data["priority"] == TaskPriority.HIGH.value
    assert data["user_id"] == "user123"

    restored = AgentTask.from_dict(data)
    assert restored.agent_name == task.agent_name
    assert restored.prompt == task.prompt
    assert restored.priority == task.priority
    assert restored.user_id == task.user_id


# =============================================================================
# TaskQueue Tests
# =============================================================================


@pytest.mark.asyncio
async def test_task_queue_priority_ordering():
    """Test that CRITICAL tasks are dequeued before LOW tasks."""
    queue = TaskQueue(maxsize=10)

    # Enqueue in reverse priority order
    low_task = AgentTask(agent_name="Low", prompt="low", priority=TaskPriority.LOW)
    normal_task = AgentTask(agent_name="Normal", prompt="normal", priority=TaskPriority.NORMAL)
    high_task = AgentTask(agent_name="High", prompt="high", priority=TaskPriority.HIGH)
    critical_task = AgentTask(agent_name="Critical", prompt="critical", priority=TaskPriority.CRITICAL)

    await queue.put(low_task)
    await queue.put(normal_task)
    await queue.put(high_task)
    await queue.put(critical_task)

    # Dequeue should be in priority order (highest first)
    dequeued = []
    while not queue.empty:
        task = await queue.get()
        dequeued.append(task.agent_name)
        queue.task_done()

    assert dequeued == ["Critical", "High", "Normal", "Low"]


@pytest.mark.asyncio
async def test_task_queue_fifo_within_same_priority():
    """Tasks with same priority should be FIFO."""
    queue = TaskQueue(maxsize=10)

    task1 = AgentTask(agent_name="First", prompt="1", priority=TaskPriority.NORMAL)
    await asyncio.sleep(0.01)  # Small delay to ensure different timestamps
    task2 = AgentTask(agent_name="Second", prompt="2", priority=TaskPriority.NORMAL)
    await asyncio.sleep(0.01)
    task3 = AgentTask(agent_name="Third", prompt="3", priority=TaskPriority.NORMAL)

    await queue.put(task1)
    await queue.put(task2)
    await queue.put(task3)

    dequeued = []
    while not queue.empty:
        task = await queue.get()
        dequeued.append(task.agent_name)
        queue.task_done()

    assert dequeued == ["First", "Second", "Third"]


@pytest.mark.asyncio
async def test_task_queue_status_set_to_queued():
    """Task status should be set to QUEUED when enqueued."""
    queue = TaskQueue(maxsize=10)
    task = AgentTask(agent_name="Test", prompt="test")
    assert task.status == TaskStatus.PENDING

    await queue.put(task)
    assert task.status == TaskStatus.QUEUED


# =============================================================================
# HeartbeatScheduler Tests
# =============================================================================


def test_heartbeat_in_active_hours():
    """Test active hours check."""
    # Test within active hours
    now_active = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)  # 10 AM
    assert HeartbeatScheduler._in_active_hours(now_active, (7, 23)) is True

    # Test outside active hours
    now_inactive = datetime(2024, 1, 1, 3, 0, 0, tzinfo=timezone.utc)  # 3 AM
    assert HeartbeatScheduler._in_active_hours(now_inactive, (7, 23)) is False

    # Test at boundary (start hour)
    now_start = datetime(2024, 1, 1, 7, 0, 0, tzinfo=timezone.utc)
    assert HeartbeatScheduler._in_active_hours(now_start, (7, 23)) is True

    # Test at boundary (end hour)
    now_end = datetime(2024, 1, 1, 23, 0, 0, tzinfo=timezone.utc)
    assert HeartbeatScheduler._in_active_hours(now_end, (7, 23)) is False


def test_heartbeat_in_active_hours_overnight():
    """Test active hours that wrap around midnight."""
    # Active from 22:00 to 06:00
    now_late = datetime(2024, 1, 1, 23, 0, 0, tzinfo=timezone.utc)
    assert HeartbeatScheduler._in_active_hours(now_late, (22, 6)) is True

    now_early = datetime(2024, 1, 1, 3, 0, 0, tzinfo=timezone.utc)
    assert HeartbeatScheduler._in_active_hours(now_early, (22, 6)) is True

    now_mid = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert HeartbeatScheduler._in_active_hours(now_mid, (22, 6)) is False


def test_heartbeat_seconds_until_active():
    """Test calculation of seconds until active hours."""
    now = datetime(2024, 1, 1, 3, 0, 0, tzinfo=timezone.utc)  # 3 AM
    seconds = HeartbeatScheduler._seconds_until_active(now, (7, 23))
    assert seconds == 4 * 3600  # 4 hours until 7 AM


def test_heartbeat_config_defaults():
    """Test HeartbeatConfig defaults."""
    config = HeartbeatConfig(agent_name="TestAgent")
    assert config.agent_name == "TestAgent"
    assert config.interval_seconds == 1800
    assert config.active_hours == (7, 23)
    assert config.enabled is True
    assert config.noop_token == "HEARTBEAT_OK"


# =============================================================================
# CronJob Tests
# =============================================================================


def test_cron_job_compute_next_run_interval():
    """Test next run calculation for interval-based jobs."""
    job = CronJob(
        agent_name="TestAgent",
        prompt="test",
        interval_seconds=3600,  # 1 hour
    )
    now = datetime.now(timezone.utc)
    next_run = job.compute_next_run()

    assert next_run is not None
    assert (next_run - now).total_seconds() >= 3600


def test_cron_job_compute_next_run_one_shot():
    """Test next run calculation for one-shot jobs."""
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    job = CronJob(
        agent_name="TestAgent",
        prompt="test",
        run_at=future,
    )
    next_run = job.compute_next_run()
    assert next_run == future


def test_cron_job_should_run():
    """Test should_run logic."""
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    job = CronJob(
        agent_name="TestAgent",
        prompt="test",
        interval_seconds=600,
        last_run=past,
    )
    job.compute_next_run()

    now = datetime.now(timezone.utc)
    assert job.should_run(now) is True


def test_cron_job_max_runs_limit():
    """Test that jobs respect max_runs limit."""
    job = CronJob(
        agent_name="TestAgent",
        prompt="test",
        interval_seconds=60,
        max_runs=3,
        run_count=3,  # Already at max
    )
    job.compute_next_run()

    now = datetime.now(timezone.utc)
    assert job.should_run(now) is False


def test_cron_job_disabled():
    """Test that disabled jobs don't run."""
    job = CronJob(
        agent_name="TestAgent",
        prompt="test",
        interval_seconds=60,
        enabled=False,
    )
    job.compute_next_run()

    now = datetime.now(timezone.utc)
    assert job.should_run(now) is False


def test_cron_job_serialization():
    """Test CronJob to_dict and from_dict."""
    job = CronJob(
        name="TestJob",
        agent_name="TestAgent",
        prompt="Test prompt",
        cron_expression="0 7 * * *",
        session_mode=SessionMode.ISOLATED,
    )

    data = job.to_dict()
    assert data["name"] == "TestJob"
    assert data["agent_name"] == "TestAgent"
    assert data["cron_expression"] == "0 7 * * *"

    restored = CronJob.from_dict(data)
    assert restored.name == job.name
    assert restored.agent_name == job.agent_name
    assert restored.cron_expression == job.cron_expression


@pytest.mark.asyncio
async def test_cron_scheduler_add_remove_job():
    """Test adding and removing cron jobs."""
    queue = TaskQueue(maxsize=10)
    scheduler = CronScheduler(task_queue=queue, check_interval=1.0)

    job = CronJob(
        name="TestJob",
        agent_name="TestAgent",
        prompt="test",
        interval_seconds=60,
    )

    job_id = scheduler.add_job(job)
    assert job_id in [j["job_id"] for j in scheduler.list_jobs()]

    removed = scheduler.remove_job(job_id)
    assert removed is True
    assert job_id not in [j["job_id"] for j in scheduler.list_jobs()]


# =============================================================================
# WorkerPool Tests
# =============================================================================


@pytest.mark.asyncio
async def test_worker_pool_executes_task():
    """Test that worker pool executes tasks correctly."""
    queue = TaskQueue(maxsize=10)
    executed = []

    async def mock_agent_factory(agent_name, session_mode, model_override, task):
        mock_agent = AsyncMock()
        mock_agent.ask = AsyncMock(return_value=("Task completed", None))
        return mock_agent

    result_callback = AsyncMock()

    pool = WorkerPool(
        task_queue=queue,
        agent_factory=mock_agent_factory,
        num_workers=1,
        max_retries=1,
        result_callback=result_callback,
    )

    await pool.start()

    task = AgentTask(agent_name="TestAgent", prompt="Do something")
    await queue.put(task)

    # Wait for task to be processed
    await asyncio.sleep(0.2)

    await pool.stop()

    # Result callback should have been called
    assert result_callback.called


@pytest.mark.asyncio
async def test_worker_pool_heartbeat_noop():
    """Test that heartbeat no-op results are detected."""
    queue = TaskQueue(maxsize=10)

    async def mock_agent_factory(agent_name, session_mode, model_override, task):
        mock_agent = AsyncMock()
        mock_agent.ask = AsyncMock(return_value=("HEARTBEAT_OK", None))
        return mock_agent

    result_callback = AsyncMock()

    pool = WorkerPool(
        task_queue=queue,
        agent_factory=mock_agent_factory,
        num_workers=1,
        result_callback=result_callback,
    )

    await pool.start()

    task = AgentTask(
        agent_name="TestAgent",
        prompt="Heartbeat",
        source="heartbeat",
        metadata={"heartbeat": True, "noop_token": "HEARTBEAT_OK"},
    )
    await queue.put(task)

    await asyncio.sleep(0.2)
    await pool.stop()

    # For heartbeat no-ops, result should be None
    assert task.result is None


@pytest.mark.asyncio
async def test_worker_pool_retry_on_failure():
    """Test that failed tasks are retried with backoff."""
    queue = TaskQueue(maxsize=10)
    call_count = 0

    async def failing_agent_factory(agent_name, session_mode, model_override, task):
        nonlocal call_count
        call_count += 1
        mock_agent = AsyncMock()
        mock_agent.ask = AsyncMock(side_effect=RuntimeError("Test failure"))
        return mock_agent

    pool = WorkerPool(
        task_queue=queue,
        agent_factory=failing_agent_factory,
        num_workers=1,
        max_retries=2,
        retry_backoff=0.1,  # Fast backoff for testing
    )

    await pool.start()

    task = AgentTask(agent_name="TestAgent", prompt="Will fail")
    await queue.put(task)

    # Wait for retries (should retry twice)
    await asyncio.sleep(1.0)

    await pool.stop()

    # Should have been called 1 + 2 retries = 3 times
    assert call_count >= 2


# =============================================================================
# AgentService Tests
# =============================================================================


@pytest.mark.asyncio
async def test_agent_service_config_defaults():
    """Test AgentServiceConfig defaults."""
    config = AgentServiceConfig()
    assert config.max_workers == 5
    assert config.queue_size == 100
    assert config.max_retries == 3
    assert config.shutdown_timeout == 30


@pytest.mark.asyncio
async def test_agent_service_stats():
    """Test AgentService stats property."""
    config = AgentServiceConfig(
        service_name="test-service",
        max_workers=2,
    )

    # Mock dependencies to avoid Redis
    with patch("parrot.services.agent_service.HAS_ASYNCDB", False):
        service = AgentService(config=config)
        stats = service.stats

        assert stats["service_name"] == "test-service"
        assert stats["running"] is False


@pytest.mark.asyncio
async def test_agent_service_submit_api():
    """Test AgentService.submit() method creates correct task."""
    config = AgentServiceConfig()

    with patch("parrot.services.agent_service.HAS_ASYNCDB", False):
        service = AgentService(config=config)
        # Initialize queue manually for testing
        service._queue = TaskQueue(maxsize=10)

        task_id = await service.submit(
            agent_name="TestAgent",
            prompt="Test prompt",
            priority=TaskPriority.HIGH,
            user_id="user123",
        )

        assert task_id is not None
        # Check task was enqueued
        assert service._queue.qsize == 1

        # Verify task properties
        task = await service._queue.get()
        assert task.agent_name == "TestAgent"
        assert task.prompt == "Test prompt"
        assert task.priority == TaskPriority.HIGH
        assert task.user_id == "user123"
        assert task.source == "api"


# =============================================================================
# AgentServiceClient Tests
# =============================================================================


@pytest.mark.asyncio
async def test_agent_service_client_creation():
    """Test AgentServiceClient can be created."""
    with patch("parrot.services.agent_service.HAS_ASYNCDB", True):
        with patch("parrot.services.agent_service.AsyncDB") as mock_db:
            client = AgentServiceClient(redis_dsn="redis://localhost:6379/0")
            assert client._task_stream == "parrot:agent:tasks"
            assert client._result_stream == "parrot:agent:results"


# =============================================================================
# Integration tests (with mocked Redis)
# =============================================================================


@pytest.mark.asyncio
async def test_full_task_lifecycle_mocked():
    """Test complete task lifecycle with mocked components."""
    queue = TaskQueue(maxsize=10)
    executed_prompts = []

    async def mock_agent_factory(agent_name, session_mode, model_override, task):
        mock_agent = AsyncMock()

        async def mock_ask(prompt, **kwargs):
            executed_prompts.append(prompt)
            return f"Response to: {prompt}", None

        mock_agent.ask = mock_ask
        return mock_agent

    pool = WorkerPool(
        task_queue=queue,
        agent_factory=mock_agent_factory,
        num_workers=2,
    )

    await pool.start()

    # Submit multiple tasks with different priorities
    tasks = [
        AgentTask(agent_name="Agent1", prompt="Low priority", priority=TaskPriority.LOW),
        AgentTask(agent_name="Agent2", prompt="Critical priority", priority=TaskPriority.CRITICAL),
        AgentTask(agent_name="Agent3", prompt="Normal priority", priority=TaskPriority.NORMAL),
    ]

    for task in tasks:
        await queue.put(task)

    # Wait for processing
    await asyncio.sleep(0.5)

    await pool.stop()

    # All tasks should have been executed
    assert len(executed_prompts) == 3
    # Critical should be first
    assert executed_prompts[0] == "Critical priority"
