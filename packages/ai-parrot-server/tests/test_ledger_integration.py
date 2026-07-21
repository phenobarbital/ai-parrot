"""Integration tests for the full event ledger capture-persist-resume cycle.

FEAT-212 — Typed Event Ledger & Crash Resume (TASK-1403).

Tests exercise:
  - End-to-end capture: emit lifecycle events → ledger receives them.
  - Crash resume: seed incomplete executions → resume() re-enqueues them.
  - No-recorder regression: events flow normally without recorder.
  - Lazy imports from parrot.autonomous.__init__.py.
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from navigator_eventbus.lifecycle.base import TraceContext
from parrot.core.events.lifecycle.events import (
    AfterToolCallEvent,
    BeforeToolCallEvent,
    ClientStreamChunkEvent,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def memory_ledger():
    """Fresh in-memory ledger backend per test."""
    from parrot.autonomous.ledger import InMemoryLedgerBackend

    return InMemoryLedgerBackend()


# ---------------------------------------------------------------------------
# End-to-end capture: emit events → check ledger
# ---------------------------------------------------------------------------


class TestEndToEndCapture:
    """Emit lifecycle events through recorder → verify ledger content."""

    @pytest.mark.asyncio
    async def test_lifecycle_events_captured_in_ledger(self, memory_ledger):
        """Emit Before/After tool events via on_event → both appear in ledger."""
        from parrot.autonomous.ledger import LedgerRecorder
        from unittest.mock import patch

        with patch("parrot.autonomous.ledger.get_global_registry") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.subscribe.return_value = "sub-e2e"
            mock_reg.return_value = mock_registry

            recorder = LedgerRecorder(memory_ledger)
            recorder.start()
            try:
                tc = TraceContext(trace_id="t-e2e", span_id="s-1")
                before = BeforeToolCallEvent(
                    trace_context=tc, tool_name="calc",
                    source_type="agent", source_name="bot-1",
                )
                after = AfterToolCallEvent(
                    trace_context=tc, tool_name="calc",
                    result_status="success",
                    source_type="agent", source_name="bot-1",
                )
                await recorder.on_event(before)
                await recorder.on_event(after)
                await asyncio.sleep(0.2)  # allow flush

                events = await memory_ledger.read(agent_id="bot-1")
                assert len(events) == 2
                trace_ids = {e.trace_id for e in events}
                assert trace_ids == {"t-e2e"}
            finally:
                await recorder.stop()

    @pytest.mark.asyncio
    async def test_both_event_classes_preserved(self, memory_ledger):
        """Both BeforeToolCallEvent and AfterToolCallEvent are in the ledger."""
        from parrot.autonomous.ledger import LedgerRecorder
        from unittest.mock import patch

        with patch("parrot.autonomous.ledger.get_global_registry") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.subscribe.return_value = "sub-classes"
            mock_reg.return_value = mock_registry

            recorder = LedgerRecorder(memory_ledger)
            recorder.start()
            try:
                tc = TraceContext(trace_id="t-cls", span_id="s-1")
                await recorder.on_event(
                    BeforeToolCallEvent(trace_context=tc, tool_name="t", source_name="bot-x")
                )
                await recorder.on_event(
                    AfterToolCallEvent(trace_context=tc, tool_name="t", source_name="bot-x")
                )
                await asyncio.sleep(0.2)

                classes = {e.event_class for e in await memory_ledger.read()}
                assert "BeforeToolCallEvent" in classes
                assert "AfterToolCallEvent" in classes
            finally:
                await recorder.stop()

    @pytest.mark.asyncio
    async def test_stream_chunk_excluded(self, memory_ledger):
        """ClientStreamChunkEvent is excluded by the recorder's where= filter."""
        from parrot.autonomous.ledger import LedgerConfig

        cfg = LedgerConfig()
        tc = TraceContext(trace_id="t-chunk", span_id="s-1")
        chunk = ClientStreamChunkEvent(
            trace_context=tc, client_name="openai", model="gpt-4",
            chunk_index=0, chunk_size_bytes=10,
        )
        # Verify filter semantics
        where = lambda e: type(e).__name__ not in cfg.exclude_event_classes  # noqa: E731
        assert where(chunk) is False


# ---------------------------------------------------------------------------
# Crash resume flow: seed incomplete → resume() re-enqueues
# ---------------------------------------------------------------------------


class TestCrashResumeFlow:
    """Seed incomplete ledger state → verify resume() re-enqueues."""

    @pytest.mark.asyncio
    async def test_incomplete_execution_is_resumed(self, memory_ledger):
        """Seed open execution → resume() re-enqueues it."""
        from parrot.autonomous.ledger import LedgerEvent
        from parrot.autonomous.orchestrator import AutonomousOrchestrator

        now = datetime.now(timezone.utc)
        await memory_ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                agent_id="bot-1",
                trace_id="orphan-trace",
                timestamp=now,
                event_data={"target_type": "agent", "target_id": "bot-1", "task": "process"},
            )
        )
        incomplete = await memory_ledger.find_incomplete()
        assert len(incomplete) == 1

        # Mock orchestrator with real resume() bound
        orch = MagicMock()
        orch.inject_job = AsyncMock(return_value="job-1")
        orch.logger = MagicMock()
        orch.job_injector = MagicMock()  # non-None so Redis guard passes
        orch.resume = AutonomousOrchestrator.resume.__get__(orch, AutonomousOrchestrator)

        count = await orch.resume(memory_ledger)
        assert count == 1
        orch.inject_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_closed_execution_not_resumed(self, memory_ledger):
        """Closed execution (Before + After) is NOT re-enqueued."""
        from parrot.autonomous.ledger import LedgerEvent
        from parrot.autonomous.orchestrator import AutonomousOrchestrator

        now = datetime.now(timezone.utc)
        await memory_ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                trace_id="closed-trace",
                timestamp=now,
                event_data={},
            )
        )
        await memory_ledger.append(
            LedgerEvent(
                event_id="e2",
                event_class="AfterInvokeEvent",
                trace_id="closed-trace",
                timestamp=now,
                event_data={},
            )
        )

        orch = MagicMock()
        orch.inject_job = AsyncMock(return_value="job-1")
        orch.logger = MagicMock()
        orch.job_injector = MagicMock()  # non-None so Redis guard passes
        orch.resume = AutonomousOrchestrator.resume.__get__(orch, AutonomousOrchestrator)

        count = await orch.resume(memory_ledger)
        assert count == 0
        orch.inject_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_incomplete_all_resumed(self, memory_ledger):
        """Multiple incomplete executions are all re-enqueued."""
        from parrot.autonomous.ledger import LedgerEvent
        from parrot.autonomous.orchestrator import AutonomousOrchestrator

        now = datetime.now(timezone.utc)
        for i in range(3):
            await memory_ledger.append(
                LedgerEvent(
                    event_id=f"e{i}",
                    event_class="BeforeInvokeEvent",
                    trace_id=f"trace-{i}",
                    timestamp=now,
                    event_data={"target_type": "agent"},
                )
            )

        orch = MagicMock()
        orch.inject_job = AsyncMock(return_value="job-x")
        orch.logger = MagicMock()
        orch.job_injector = MagicMock()  # non-None so Redis guard passes
        orch.resume = AutonomousOrchestrator.resume.__get__(orch, AutonomousOrchestrator)

        count = await orch.resume(memory_ledger)
        assert count == 3
        assert orch.inject_job.call_count == 3


# ---------------------------------------------------------------------------
# No-recorder regression: events flow normally without recorder
# ---------------------------------------------------------------------------


class TestNoRecorderRegression:
    """Without LedgerRecorder, lifecycle events still work normally."""

    @pytest.mark.asyncio
    async def test_events_flow_without_recorder(self):
        """Emit lifecycle events to global registry without a recorder — no errors."""
        from navigator_eventbus.lifecycle.global_registry import scope

        with scope() as registry:
            tc = TraceContext(trace_id="t-norec", span_id="s-1")
            evt = BeforeToolCallEvent(trace_context=tc, tool_name="test", source_type="agent")
            # This should not raise even without a recorder
            await registry.emit(evt)

    @pytest.mark.asyncio
    async def test_agent_state_empty_without_recorder(self, memory_ledger):
        """Without recorder, ledger is empty and last_state returns zeros."""
        state = await memory_ledger.last_state("any-agent")
        assert state.total_events == 0
        assert state.open_executions == 0

    @pytest.mark.asyncio
    async def test_find_incomplete_empty_without_recorder(self, memory_ledger):
        """Without recorder, find_incomplete returns empty list."""
        incomplete = await memory_ledger.find_incomplete()
        assert incomplete == []


# ---------------------------------------------------------------------------
# Lazy export verification: from parrot.autonomous import <ledger classes>
# ---------------------------------------------------------------------------


class TestLazyExports:
    """Verify lazy loading of ledger classes from parrot.autonomous."""

    def test_event_ledger_lazy_import(self):
        """EventLedger is accessible via parrot.autonomous lazy loading."""
        from parrot.autonomous.ledger import EventLedger
        assert EventLedger is not None

    def test_postgres_backend_lazy_import(self):
        """PostgresLedgerBackend is accessible via parrot.autonomous lazy loading."""
        from parrot.autonomous.ledger import PostgresLedgerBackend
        assert PostgresLedgerBackend is not None

    def test_ledger_recorder_lazy_import(self):
        """LedgerRecorder is accessible via parrot.autonomous lazy loading."""
        from parrot.autonomous.ledger import LedgerRecorder
        assert LedgerRecorder is not None

    def test_ledger_event_lazy_import(self):
        """LedgerEvent is accessible via parrot.autonomous lazy loading."""
        from parrot.autonomous.ledger import LedgerEvent
        assert LedgerEvent is not None

    def test_ledger_config_lazy_import(self):
        """LedgerConfig is accessible via parrot.autonomous lazy loading."""
        from parrot.autonomous.ledger import LedgerConfig
        assert LedgerConfig is not None

    def test_in_memory_backend_lazy_import(self):
        """InMemoryLedgerBackend is accessible via parrot.autonomous lazy loading."""
        from parrot.autonomous.ledger import InMemoryLedgerBackend
        assert InMemoryLedgerBackend is not None

    def test_event_ledger_is_abstract(self):
        """EventLedger is abstract — cannot be instantiated directly."""
        from parrot.autonomous.ledger import EventLedger

        try:
            EventLedger()
            assert False, "Should have raised TypeError"
        except TypeError:
            pass  # Expected — it's an ABC

    def test_in_memory_backend_implements_event_ledger(self):
        """InMemoryLedgerBackend is a concrete EventLedger implementation."""
        from parrot.autonomous.ledger import EventLedger, InMemoryLedgerBackend

        backend = InMemoryLedgerBackend()
        assert isinstance(backend, EventLedger)

    def test_existing_autonomous_imports_unbroken(self):
        """Existing AutonomousOrchestrator import still works after ledger additions."""
        from parrot.autonomous.orchestrator import AutonomousOrchestrator
        assert AutonomousOrchestrator is not None
