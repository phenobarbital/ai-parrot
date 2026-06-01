"""Unit tests for EventLedger ABC + InMemoryLedgerBackend.

FEAT-212 — Typed Event Ledger & Crash Resume (TASK-1400).

Tests use InMemoryLedgerBackend (no Postgres required in CI).
The PostgresLedgerBackend follows the same interface and semantics.
"""
import pytest
from datetime import datetime, timezone

from parrot.autonomous.ledger import (
    LedgerEvent,
    InMemoryLedgerBackend,
    LedgerConfig,
    AgentLedgerState,
    IncompleteExecution,
)


@pytest.fixture
def memory_ledger():
    """Fresh in-memory ledger backend per test."""
    return InMemoryLedgerBackend()


class TestLedgerBackendAppend:
    """Tests for append() monotonic seq guarantee."""

    @pytest.mark.asyncio
    async def test_append_returns_monotonic_seq(self, memory_ledger):
        """append() assigns monotonically increasing seq values."""
        e1 = LedgerEvent(
            event_id="e1",
            event_class="BeforeInvokeEvent",
            timestamp=datetime.now(timezone.utc),
            event_data={},
        )
        e2 = LedgerEvent(
            event_id="e2",
            event_class="AfterInvokeEvent",
            timestamp=datetime.now(timezone.utc),
            event_data={},
        )
        s1 = await memory_ledger.append(e1)
        s2 = await memory_ledger.append(e2)
        assert s2 > s1

    @pytest.mark.asyncio
    async def test_append_seq_starts_at_one(self, memory_ledger):
        """First appended event gets seq=1."""
        e = LedgerEvent(
            event_id="e1",
            event_class="X",
            timestamp=datetime.now(timezone.utc),
            event_data={},
        )
        seq = await memory_ledger.append(e)
        assert seq == 1

    @pytest.mark.asyncio
    async def test_append_stores_event(self, memory_ledger):
        """Appended event is retrievable via read()."""
        e = LedgerEvent(
            event_id="e1",
            event_class="BeforeToolCallEvent",
            agent_id="bot-1",
            timestamp=datetime.now(timezone.utc),
            event_data={"tool_name": "calc"},
        )
        await memory_ledger.append(e)
        results = await memory_ledger.read()
        assert len(results) == 1
        assert results[0].event_id == "e1"


class TestLedgerBackendRead:
    """Tests for read() filter semantics."""

    @pytest.mark.asyncio
    async def test_read_filters_by_agent_id(self, memory_ledger):
        """read(agent_id=) returns only events for that agent."""
        for aid in ("a1", "a2", "a1"):
            await memory_ledger.append(
                LedgerEvent(
                    event_id=f"e-{aid}-{aid}",
                    event_class="X",
                    agent_id=aid,
                    timestamp=datetime.now(timezone.utc),
                    event_data={},
                )
            )
        results = await memory_ledger.read(agent_id="a1")
        assert len(results) == 2
        assert all(r.agent_id == "a1" for r in results)

    @pytest.mark.asyncio
    async def test_read_filters_by_event_class(self, memory_ledger):
        """read(event_class=) returns only events of that class."""
        await memory_ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                timestamp=datetime.now(timezone.utc),
                event_data={},
            )
        )
        await memory_ledger.append(
            LedgerEvent(
                event_id="e2",
                event_class="AfterInvokeEvent",
                timestamp=datetime.now(timezone.utc),
                event_data={},
            )
        )
        results = await memory_ledger.read(event_class="BeforeInvokeEvent")
        assert len(results) == 1
        assert results[0].event_class == "BeforeInvokeEvent"

    @pytest.mark.asyncio
    async def test_read_filters_by_since_seq(self, memory_ledger):
        """read(since_seq=N) returns only events with seq > N."""
        for i in range(5):
            await memory_ledger.append(
                LedgerEvent(
                    event_id=f"e{i}",
                    event_class="X",
                    timestamp=datetime.now(timezone.utc),
                    event_data={},
                )
            )
        results = await memory_ledger.read(since_seq=3)
        assert len(results) == 2
        assert all((r.seq or 0) > 3 for r in results)

    @pytest.mark.asyncio
    async def test_read_respects_limit(self, memory_ledger):
        """read(limit=N) returns at most N events."""
        for i in range(10):
            await memory_ledger.append(
                LedgerEvent(
                    event_id=f"e{i}",
                    event_class="X",
                    timestamp=datetime.now(timezone.utc),
                    event_data={},
                )
            )
        results = await memory_ledger.read(limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_read_ordered_by_seq(self, memory_ledger):
        """Events are returned ordered by seq ascending."""
        for i in range(5):
            await memory_ledger.append(
                LedgerEvent(
                    event_id=f"e{i}",
                    event_class="X",
                    timestamp=datetime.now(timezone.utc),
                    event_data={},
                )
            )
        results = await memory_ledger.read()
        seqs = [r.seq for r in results]
        assert seqs == sorted(seqs)

    @pytest.mark.asyncio
    async def test_read_no_filters_returns_all(self, memory_ledger):
        """read() without filters returns all events (up to limit)."""
        for i in range(3):
            await memory_ledger.append(
                LedgerEvent(
                    event_id=f"e{i}",
                    event_class="X",
                    timestamp=datetime.now(timezone.utc),
                    event_data={},
                )
            )
        results = await memory_ledger.read()
        assert len(results) == 3


class TestLastStateProjection:
    """Tests for last_state() agent projection."""

    @pytest.mark.asyncio
    async def test_last_state_returns_agent_ledger_state(self, memory_ledger):
        """last_state() returns an AgentLedgerState instance."""
        now = datetime.now(timezone.utc)
        await memory_ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                agent_id="bot-1",
                trace_id="t1",
                timestamp=now,
                event_data={},
            )
        )
        state = await memory_ledger.last_state("bot-1")
        assert isinstance(state, AgentLedgerState)
        assert state.agent_id == "bot-1"

    @pytest.mark.asyncio
    async def test_last_state_closed_execution(self, memory_ledger):
        """Closed trace (Before + After) is counted as closed, not open."""
        now = datetime.now(timezone.utc)
        await memory_ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                agent_id="bot-1",
                trace_id="t1",
                timestamp=now,
                event_data={},
            )
        )
        await memory_ledger.append(
            LedgerEvent(
                event_id="e2",
                event_class="AfterInvokeEvent",
                agent_id="bot-1",
                trace_id="t1",
                timestamp=now,
                event_data={},
            )
        )
        state = await memory_ledger.last_state("bot-1")
        assert state.last_activity is not None
        assert state.open_executions == 0
        assert state.closed_executions == 1

    @pytest.mark.asyncio
    async def test_last_state_open_execution(self, memory_ledger):
        """Open trace (Before without After) is counted as open."""
        now = datetime.now(timezone.utc)
        await memory_ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                agent_id="bot-1",
                trace_id="open-t1",
                timestamp=now,
                event_data={},
            )
        )
        state = await memory_ledger.last_state("bot-1")
        assert state.open_executions == 1
        assert state.closed_executions == 0

    @pytest.mark.asyncio
    async def test_last_state_empty_agent(self, memory_ledger):
        """last_state() for unknown agent returns zero counts."""
        state = await memory_ledger.last_state("unknown-agent")
        assert state.last_activity is None
        assert state.open_executions == 0
        assert state.total_events == 0

    @pytest.mark.asyncio
    async def test_last_state_total_events(self, memory_ledger):
        """total_events reflects all events for the agent."""
        now = datetime.now(timezone.utc)
        for i in range(4):
            await memory_ledger.append(
                LedgerEvent(
                    event_id=f"e{i}",
                    event_class="X",
                    agent_id="bot-x",
                    timestamp=now,
                    event_data={},
                )
            )
        state = await memory_ledger.last_state("bot-x")
        assert state.total_events == 4


class TestFindIncomplete:
    """Tests for find_incomplete() logic."""

    @pytest.mark.asyncio
    async def test_find_incomplete_detects_open(self, memory_ledger):
        """Before* without After* is detected as incomplete."""
        now = datetime.now(timezone.utc)
        # Open execution (Before without After)
        await memory_ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                agent_id="bot-1",
                trace_id="open-trace",
                timestamp=now,
                event_data={},
            )
        )
        # Closed execution
        await memory_ledger.append(
            LedgerEvent(
                event_id="e2",
                event_class="BeforeInvokeEvent",
                agent_id="bot-1",
                trace_id="closed-trace",
                timestamp=now,
                event_data={},
            )
        )
        await memory_ledger.append(
            LedgerEvent(
                event_id="e3",
                event_class="AfterInvokeEvent",
                agent_id="bot-1",
                trace_id="closed-trace",
                timestamp=now,
                event_data={},
            )
        )
        incomplete = await memory_ledger.find_incomplete()
        assert len(incomplete) == 1
        assert incomplete[0].trace_id == "open-trace"

    @pytest.mark.asyncio
    async def test_find_incomplete_empty_when_all_closed(self, memory_ledger):
        """find_incomplete() returns empty list when all traces are closed."""
        now = datetime.now(timezone.utc)
        await memory_ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                trace_id="t1",
                timestamp=now,
                event_data={},
            )
        )
        await memory_ledger.append(
            LedgerEvent(
                event_id="e2",
                event_class="AfterInvokeEvent",
                trace_id="t1",
                timestamp=now,
                event_data={},
            )
        )
        assert await memory_ledger.find_incomplete() == []

    @pytest.mark.asyncio
    async def test_find_incomplete_returns_incomplete_execution(self, memory_ledger):
        """find_incomplete() returns IncompleteExecution objects."""
        now = datetime.now(timezone.utc)
        await memory_ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeToolCallEvent",
                agent_id="bot-1",
                trace_id="tool-trace",
                timestamp=now,
                event_data={"tool_name": "calc"},
            )
        )
        incomplete = await memory_ledger.find_incomplete()
        assert len(incomplete) == 1
        assert isinstance(incomplete[0], IncompleteExecution)
        assert incomplete[0].trace_id == "tool-trace"
        assert incomplete[0].event_class == "BeforeToolCallEvent"

    @pytest.mark.asyncio
    async def test_find_incomplete_failed_counts_as_closed(self, memory_ledger):
        """*Failed events close an execution (no incomplete)."""
        now = datetime.now(timezone.utc)
        await memory_ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                trace_id="t1",
                timestamp=now,
                event_data={},
            )
        )
        await memory_ledger.append(
            LedgerEvent(
                event_id="e2",
                event_class="InvokeFailedEvent",
                trace_id="t1",
                timestamp=now,
                event_data={},
            )
        )
        assert await memory_ledger.find_incomplete() == []

    @pytest.mark.asyncio
    async def test_find_incomplete_tool_failed_counts_as_closed(self, memory_ledger):
        """ToolCallFailedEvent closes a BeforeToolCallEvent trace."""
        now = datetime.now(timezone.utc)
        await memory_ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeToolCallEvent",
                trace_id="t1",
                timestamp=now,
                event_data={},
            )
        )
        await memory_ledger.append(
            LedgerEvent(
                event_id="e2",
                event_class="ToolCallFailedEvent",
                trace_id="t1",
                timestamp=now,
                event_data={},
            )
        )
        assert await memory_ledger.find_incomplete() == []

    @pytest.mark.asyncio
    async def test_find_incomplete_multiple_open_traces(self, memory_ledger):
        """Multiple open traces are all detected as incomplete."""
        now = datetime.now(timezone.utc)
        for i in range(3):
            await memory_ledger.append(
                LedgerEvent(
                    event_id=f"e{i}",
                    event_class="BeforeInvokeEvent",
                    trace_id=f"trace-{i}",
                    timestamp=now,
                    event_data={},
                )
            )
        incomplete = await memory_ledger.find_incomplete()
        assert len(incomplete) == 3

    @pytest.mark.asyncio
    async def test_find_incomplete_events_without_trace_id_ignored(self, memory_ledger):
        """Events with trace_id=None are excluded from incomplete detection."""
        now = datetime.now(timezone.utc)
        await memory_ledger.append(
            LedgerEvent(
                event_id="e1",
                event_class="BeforeInvokeEvent",
                trace_id=None,  # no trace_id
                timestamp=now,
                event_data={},
            )
        )
        incomplete = await memory_ledger.find_incomplete()
        assert incomplete == []
