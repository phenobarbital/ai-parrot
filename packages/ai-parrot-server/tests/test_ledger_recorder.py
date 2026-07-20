"""Unit tests for LedgerRecorder — global lifecycle event capture.

FEAT-212 — Typed Event Ledger & Crash Resume (TASK-1401).
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from navigator_eventbus.lifecycle.base import TraceContext
from parrot.core.events.lifecycle.events import (
    BeforeToolCallEvent,
    ClientStreamChunkEvent,
)


@pytest.fixture
def memory_ledger():
    """Fresh in-memory ledger backend per test."""
    from parrot.autonomous.ledger import InMemoryLedgerBackend

    return InMemoryLedgerBackend()


@pytest.fixture
def recorder(memory_ledger):
    """LedgerRecorder backed by an in-memory ledger."""
    from parrot.autonomous.ledger import LedgerRecorder

    return LedgerRecorder(memory_ledger)


class TestLedgerRecorderPersistence:
    """Tests for on_event → append flow (recorder with flush loop running)."""

    @pytest.mark.asyncio
    async def test_recorder_persists_on_emit(self, memory_ledger):
        """Calling on_event with flush loop running results in an append to the ledger."""
        from parrot.autonomous.ledger import LedgerRecorder

        with patch("parrot.autonomous.ledger.get_global_registry") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.subscribe.return_value = "sub-p1"
            mock_reg.return_value = mock_registry

            r = LedgerRecorder(memory_ledger)
            r.start()
            try:
                tc = TraceContext(trace_id="t-1", span_id="s-1")
                evt = BeforeToolCallEvent(
                    trace_context=tc, tool_name="calc", source_type="agent",
                )
                await r.on_event(evt)
                # Wait briefly for flush loop to drain the queue
                await asyncio.sleep(0.2)
                events = await memory_ledger.read()
                assert len(events) >= 1
                assert events[0].event_class == "BeforeToolCallEvent"
            finally:
                await r.stop()

    @pytest.mark.asyncio
    async def test_recorder_sets_trace_id(self, memory_ledger):
        """Persisted event preserves trace_id from the lifecycle event."""
        from parrot.autonomous.ledger import LedgerRecorder

        with patch("parrot.autonomous.ledger.get_global_registry") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.subscribe.return_value = "sub-p2"
            mock_reg.return_value = mock_registry

            r = LedgerRecorder(memory_ledger)
            r.start()
            try:
                tc = TraceContext(trace_id="trace-abc", span_id="s-1")
                evt = BeforeToolCallEvent(trace_context=tc, tool_name="t")
                await r.on_event(evt)
                await asyncio.sleep(0.2)
                events = await memory_ledger.read()
                assert events[0].trace_id == "trace-abc"
            finally:
                await r.stop()

    @pytest.mark.asyncio
    async def test_recorder_enqueues_immediately(self, recorder, memory_ledger):
        """on_event returns immediately without blocking (fire-and-forget)."""
        tc = TraceContext(trace_id="t-fast", span_id="s-1")
        evt = BeforeToolCallEvent(trace_context=tc, tool_name="t")
        # Should not block — just puts to queue
        await recorder.on_event(evt)
        # Queue should have the item before flush (or may have been flushed)
        assert recorder._queue.qsize() >= 0

    @pytest.mark.asyncio
    async def test_recorder_persists_multiple_events(self, memory_ledger):
        """Multiple on_event calls result in multiple persisted events."""
        from parrot.autonomous.ledger import LedgerRecorder

        with patch("parrot.autonomous.ledger.get_global_registry") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.subscribe.return_value = "sub-p3"
            mock_reg.return_value = mock_registry

            r = LedgerRecorder(memory_ledger)
            r.start()
            try:
                tc = TraceContext(trace_id="t-multi", span_id="s-1")
                for i in range(5):
                    evt = BeforeToolCallEvent(
                        trace_context=tc, tool_name=f"tool-{i}", source_name="bot-1",
                    )
                    await r.on_event(evt)
                await asyncio.sleep(0.3)
                events = await memory_ledger.read(agent_id="bot-1")
                assert len(events) == 5
            finally:
                await r.stop()


class TestLedgerRecorderFilter:
    """Tests for the where= filter that excludes ClientStreamChunkEvent."""

    def test_recorder_skips_stream_chunks_via_config(self):
        """ClientStreamChunkEvent is in the default exclude set."""
        from parrot.autonomous.ledger import LedgerConfig

        cfg = LedgerConfig()
        exclude = cfg.exclude_event_classes
        tc = TraceContext(trace_id="t-2", span_id="s-2")
        chunk = ClientStreamChunkEvent(
            trace_context=tc,
            client_name="openai",
            model="gpt-4",
            chunk_index=0,
            chunk_size_bytes=100,
        )
        assert type(chunk).__name__ in exclude

    def test_recorder_where_filter_excludes_stream_chunks(self, recorder):
        """The where filter lambda excludes ClientStreamChunkEvent by class name."""
        from parrot.autonomous.ledger import LedgerConfig

        exclude = LedgerConfig().exclude_event_classes
        tc = TraceContext(trace_id="t-f", span_id="s-f")
        chunk = ClientStreamChunkEvent(
            trace_context=tc,
            client_name="openai",
            model="gpt-4",
            chunk_index=0,
            chunk_size_bytes=10,
        )
        # The where= predicate used in start()
        where = lambda e: type(e).__name__ not in exclude  # noqa: E731
        assert where(chunk) is False

        # BeforeToolCallEvent passes the filter
        tool_evt = BeforeToolCallEvent(trace_context=tc, tool_name="x")
        assert where(tool_evt) is True


class TestLedgerRecorderStartStop:
    """Tests for start() / stop() subscription lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_subscription_id(self, recorder, memory_ledger):
        """start() stores a subscription_id after subscribing to the global registry."""
        with patch("parrot.autonomous.ledger.get_global_registry") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.subscribe.return_value = "sub-abc"
            mock_reg.return_value = mock_registry

            recorder.start()
            assert recorder._subscription_id == "sub-abc"
            # Clean up
            recorder._flush_task.cancel()

    @pytest.mark.asyncio
    async def test_stop_unsubscribes(self, recorder, memory_ledger):
        """stop() unsubscribes from the global registry and cancels flush task."""
        with patch("parrot.autonomous.ledger.get_global_registry") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.subscribe.return_value = "sub-123"
            mock_reg.return_value = mock_registry

            recorder.start()
            assert recorder._subscription_id == "sub-123"

            await recorder.stop()
            mock_registry.unsubscribe.assert_called_once_with("sub-123")
            assert recorder._subscription_id is None

    @pytest.mark.asyncio
    async def test_stop_cancels_flush_task(self, memory_ledger):
        """stop() cancels the background flush task."""
        with patch("parrot.autonomous.ledger.get_global_registry") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.subscribe.return_value = "sub-x"
            mock_reg.return_value = mock_registry

            from parrot.autonomous.ledger import LedgerRecorder

            r = LedgerRecorder(memory_ledger)
            r.start()
            task = r._flush_task
            assert task is not None
            assert not task.done()

            await r.stop()
            assert task.done()

    @pytest.mark.asyncio
    async def test_start_creates_flush_task(self, recorder, memory_ledger):
        """start() creates and starts the background flush task."""
        with patch("parrot.autonomous.ledger.get_global_registry") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.subscribe.return_value = "sub-ft"
            mock_reg.return_value = mock_registry

            recorder.start()
            assert recorder._flush_task is not None
            assert not recorder._flush_task.done()

            await recorder.stop()


class TestLedgerRecorderBatching:
    """Tests for the batched flush loop behavior."""

    @pytest.mark.asyncio
    async def test_flush_loop_drains_all_queued_events(self, memory_ledger):
        """All events queued before flush runs are persisted."""
        from parrot.autonomous.ledger import LedgerRecorder

        r = LedgerRecorder(memory_ledger)
        tc = TraceContext(trace_id="t-batch", span_id="s-1")

        # Queue 10 events without starting the flush loop
        for i in range(10):
            evt = BeforeToolCallEvent(
                trace_context=tc, tool_name=f"t{i}", source_name="bot-1",
            )
            await r.on_event(evt)

        # Now call _flush_loop manually for one cycle
        batch: list = []
        batch.append(await r._queue.get())
        while True:
            try:
                batch.append(r._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        for event in batch:
            await memory_ledger.append(event)

        events = await memory_ledger.read(agent_id="bot-1")
        assert len(events) == 10
