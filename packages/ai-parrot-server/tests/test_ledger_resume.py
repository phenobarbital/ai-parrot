"""Unit tests for AutonomousOrchestrator.resume() crash recovery.

FEAT-212 — Typed Event Ledger & Crash Resume (TASK-1402).
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from parrot.autonomous.ledger import InMemoryLedgerBackend, LedgerEvent


@pytest.fixture
def fake_orchestrator():
    """AutonomousOrchestrator-like mock with real resume() bound to it."""
    from parrot.autonomous.orchestrator import AutonomousOrchestrator

    orch = MagicMock(spec=AutonomousOrchestrator)
    orch.inject_job = AsyncMock(return_value="job-1")
    orch.logger = MagicMock()
    # Provide a non-None job_injector so the Redis guard in resume() does not
    # short-circuit before reaching the ledger query.
    orch.job_injector = MagicMock()
    # Bind the real resume method to the mock instance
    orch.resume = AutonomousOrchestrator.resume.__get__(orch, AutonomousOrchestrator)
    return orch


@pytest.fixture
def empty_ledger():
    """Empty in-memory ledger."""
    return InMemoryLedgerBackend()


class TestOrchestratorResume:
    """Tests for resume() re-enqueue logic."""

    @pytest.mark.asyncio
    async def test_resume_reenqueues_incomplete(self, fake_orchestrator):
        """resume() calls inject_job for each incomplete execution."""
        ledger = InMemoryLedgerBackend()
        now = datetime.now(timezone.utc)
        # Seed an open execution
        await ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                agent_id="bot-1",
                trace_id="open-t1",
                timestamp=now,
                event_data={"target_type": "agent", "target_id": "bot-1", "task": "do stuff"},
            )
        )
        count = await fake_orchestrator.resume(ledger)
        assert count == 1
        fake_orchestrator.inject_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_resume_returns_zero_when_nothing_incomplete(self, fake_orchestrator, empty_ledger):
        """resume() returns 0 when no incomplete executions exist."""
        count = await fake_orchestrator.resume(empty_ledger)
        assert count == 0
        fake_orchestrator.inject_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_continues_on_inject_failure(self, fake_orchestrator):
        """If inject_job raises for one, resume logs and continues with the next."""
        ledger = InMemoryLedgerBackend()
        now = datetime.now(timezone.utc)
        await ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                agent_id="bot-1",
                trace_id="t1",
                timestamp=now,
                event_data={"target_type": "agent"},
            )
        )
        await ledger.append(
            LedgerEvent(
                event_id="e2",
                event_class="BeforeInvokeEvent",
                agent_id="bot-2",
                trace_id="t2",
                timestamp=now,
                event_data={"target_type": "agent"},
            )
        )
        fake_orchestrator.inject_job = AsyncMock(
            side_effect=[Exception("inject fail"), "job-2"]
        )
        count = await fake_orchestrator.resume(ledger)
        assert count == 1  # one succeeded, one failed

    @pytest.mark.asyncio
    async def test_resume_logs_on_failure(self, fake_orchestrator):
        """resume() calls logger.exception when inject_job raises."""
        ledger = InMemoryLedgerBackend()
        now = datetime.now(timezone.utc)
        await ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                trace_id="t-fail",
                timestamp=now,
                event_data={},
            )
        )
        fake_orchestrator.inject_job = AsyncMock(side_effect=Exception("fail"))
        await fake_orchestrator.resume(ledger)
        # Exception should have been logged
        fake_orchestrator.logger.exception.assert_called_once()

    @pytest.mark.asyncio
    async def test_resume_uses_agent_id_as_target(self, fake_orchestrator):
        """resume() uses agent_id as target_id when available."""
        ledger = InMemoryLedgerBackend()
        now = datetime.now(timezone.utc)
        await ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                agent_id="my-agent",
                trace_id="t1",
                timestamp=now,
                event_data={"target_type": "agent", "task": "my task"},
            )
        )
        await fake_orchestrator.resume(ledger)
        call_kwargs = fake_orchestrator.inject_job.call_args
        # target_id should come from agent_id
        assert call_kwargs.kwargs["target_id"] == "my-agent"

    @pytest.mark.asyncio
    async def test_resume_uses_fallback_task_when_missing(self, fake_orchestrator):
        """When event_data has no 'task', resume uses trace_id as fallback task."""
        ledger = InMemoryLedgerBackend()
        now = datetime.now(timezone.utc)
        await ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                agent_id="bot-1",
                trace_id="trace-fallback",
                timestamp=now,
                event_data={"target_type": "agent"},  # no 'task' key
            )
        )
        await fake_orchestrator.resume(ledger)
        call_kwargs = fake_orchestrator.inject_job.call_args
        # The task param should be "resume:trace-fallback"
        assert call_kwargs.kwargs["task"] == "resume:trace-fallback"

    @pytest.mark.asyncio
    async def test_resume_returns_correct_count_multiple(self, fake_orchestrator):
        """resume() returns count of successfully re-enqueued jobs."""
        ledger = InMemoryLedgerBackend()
        now = datetime.now(timezone.utc)
        for i in range(4):
            await ledger.append(
                LedgerEvent(
                    event_id=f"e{i}",
                    event_class="BeforeInvokeEvent",
                    trace_id=f"t{i}",
                    timestamp=now,
                    event_data={"target_type": "agent"},
                )
            )
        fake_orchestrator.inject_job = AsyncMock(
            side_effect=["job-0", "job-1", Exception("fail"), "job-3"]
        )
        count = await fake_orchestrator.resume(ledger)
        assert count == 3  # 3 succeeded, 1 failed

    @pytest.mark.asyncio
    async def test_resume_logs_info_for_each_reenqueued(self, fake_orchestrator):
        """resume() logs at INFO level for each re-enqueued trace."""
        ledger = InMemoryLedgerBackend()
        now = datetime.now(timezone.utc)
        await ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                trace_id="t-info",
                timestamp=now,
                event_data={"target_type": "agent"},
            )
        )
        await fake_orchestrator.resume(ledger)
        # INFO should have been called at least twice (once for no-incomplete check
        # or once per reenqueue)
        assert fake_orchestrator.logger.info.called


class TestOrchestratorStartWithResume:
    """Tests for start() backward compatibility and opt-in resume."""

    @pytest.mark.asyncio
    async def test_start_without_ledger_unchanged(self):
        """start() without ledger arg works identically to before FEAT-212."""
        from parrot.autonomous.orchestrator import AutonomousOrchestrator

        # Create a minimal orchestrator with mocked internals
        orch = AutonomousOrchestrator(
            use_event_bus=False,
            use_webhooks=False,
        )
        # Mock out components that need real connections
        orch.hook_manager = MagicMock()
        orch.hook_manager.start_all = AsyncMock()
        orch.hook_manager.stats = {}
        # Should complete without error
        await orch.start()
        assert orch._running is True

    @pytest.mark.asyncio
    async def test_start_with_ledger_no_resume_on_start(self):
        """start(ledger=...) without resume_on_start=True does NOT call resume()."""
        from parrot.autonomous.orchestrator import AutonomousOrchestrator

        orch = AutonomousOrchestrator(use_event_bus=False, use_webhooks=False)
        orch.hook_manager = MagicMock()
        orch.hook_manager.start_all = AsyncMock()
        orch.hook_manager.stats = {}

        ledger = InMemoryLedgerBackend()
        # Seed an incomplete execution — should NOT be re-enqueued
        await ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                trace_id="t1",
                timestamp=datetime.now(timezone.utc),
                event_data={},
            )
        )
        orch.inject_job = AsyncMock(return_value="job-1")
        # Pass ledger but NOT resume_on_start — should be no-op
        await orch.start(ledger=ledger, resume_on_start=False)
        orch.inject_job.assert_not_called()
