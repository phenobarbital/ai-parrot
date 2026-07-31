"""Unit tests for LedgerEvent, LedgerConfig, AgentLedgerState, IncompleteExecution.

FEAT-212 — Typed Event Ledger & Crash Resume (TASK-1399).
"""
import json
from datetime import datetime, timezone

import pytest

from navigator_eventbus.lifecycle.base import TraceContext
from parrot.core.events.lifecycle.events import BeforeToolCallEvent, AfterToolCallEvent


class TestLedgerEvent:
    """Tests for LedgerEvent.from_lifecycle mapping."""

    def test_from_lifecycle_maps_tool_event(self):
        """LedgerEvent.from_lifecycle preserves event_id, trace_id, timestamp, event_class."""
        from parrot.autonomous.ledger import LedgerEvent

        tc = TraceContext(trace_id="t-1", span_id="s-1")
        evt = BeforeToolCallEvent(
            trace_context=tc,
            tool_name="my_tool",
            source_type="agent",
            source_name="bot-1",
        )
        le = LedgerEvent.from_lifecycle(evt)
        assert le.event_id == evt.event_id
        assert le.trace_id == "t-1"
        assert le.event_class == "BeforeToolCallEvent"
        assert le.source_type == "agent"
        assert le.source_name == "bot-1"
        assert le.agent_id == "bot-1"
        assert isinstance(le.event_data, dict)
        assert le.seq is None  # not yet persisted

    def test_from_lifecycle_event_data_is_json_safe(self):
        """event_data from to_dict() should be JSON-serializable."""
        from parrot.autonomous.ledger import LedgerEvent

        tc = TraceContext(trace_id="t-2", span_id="s-2")
        # AfterToolCallEvent uses result_status, not result
        evt = AfterToolCallEvent(
            trace_context=tc,
            tool_name="calc",
            result_status="success",
            source_type="tool",
        )
        le = LedgerEvent.from_lifecycle(evt)
        serialized = json.dumps(le.event_data)
        assert isinstance(serialized, str)

    def test_from_lifecycle_preserves_timestamp(self):
        """LedgerEvent.timestamp matches the original event's timestamp."""
        from parrot.autonomous.ledger import LedgerEvent

        tc = TraceContext(trace_id="t-3", span_id="s-3")
        evt = BeforeToolCallEvent(trace_context=tc, tool_name="t")
        le = LedgerEvent.from_lifecycle(evt)
        assert le.timestamp == evt.timestamp

    def test_from_lifecycle_sets_event_class(self):
        """event_class is the concrete class name, not 'LifecycleEvent'."""
        from parrot.autonomous.ledger import LedgerEvent

        tc = TraceContext(trace_id="t-4", span_id="s-4")
        evt = AfterToolCallEvent(trace_context=tc, tool_name="t")
        le = LedgerEvent.from_lifecycle(evt)
        assert le.event_class == "AfterToolCallEvent"

    def test_from_lifecycle_null_agent_id_when_no_source_name(self):
        """agent_id is None when source_name is empty."""
        from parrot.autonomous.ledger import LedgerEvent

        tc = TraceContext(trace_id="t-5", span_id="s-5")
        evt = BeforeToolCallEvent(trace_context=tc, tool_name="t", source_name="")
        le = LedgerEvent.from_lifecycle(evt)
        assert le.agent_id is None

    def test_from_lifecycle_event_data_contains_event_class_key(self):
        """to_dict() adds 'event_class' key — verify it's in event_data."""
        from parrot.autonomous.ledger import LedgerEvent

        tc = TraceContext(trace_id="t-6", span_id="s-6")
        evt = BeforeToolCallEvent(trace_context=tc, tool_name="t")
        le = LedgerEvent.from_lifecycle(evt)
        assert "event_class" in le.event_data
        assert le.event_data["event_class"] == "BeforeToolCallEvent"


class TestLedgerConfig:
    """Tests for LedgerConfig defaults and validation."""

    def test_ledger_config_defaults(self):
        """LedgerConfig has sensible defaults."""
        from parrot.autonomous.ledger import LedgerConfig

        cfg = LedgerConfig()
        assert cfg.enabled is True
        assert "ClientStreamChunkEvent" in cfg.exclude_event_classes
        assert cfg.batch_size == 50
        assert cfg.table_name == "harness_ledger"

    def test_ledger_config_exclude_set(self):
        """exclude_event_classes is a set, not a list."""
        from parrot.autonomous.ledger import LedgerConfig

        cfg = LedgerConfig()
        assert isinstance(cfg.exclude_event_classes, (set, frozenset))

    def test_ledger_config_custom_exclude(self):
        """Can configure additional excluded event classes."""
        from parrot.autonomous.ledger import LedgerConfig

        cfg = LedgerConfig(exclude_event_classes={"ClientStreamChunkEvent", "SomeOtherEvent"})
        assert "SomeOtherEvent" in cfg.exclude_event_classes

    def test_ledger_config_batch_size_ge_1(self):
        """batch_size must be >= 1."""
        from parrot.autonomous.ledger import LedgerConfig
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            LedgerConfig(batch_size=0)


class TestAgentLedgerState:
    """Tests for AgentLedgerState model."""

    def test_agent_ledger_state_defaults(self):
        """AgentLedgerState has sensible defaults."""
        from parrot.autonomous.ledger import AgentLedgerState

        state = AgentLedgerState(agent_id="bot-1")
        assert state.agent_id == "bot-1"
        assert state.last_activity is None
        assert state.open_executions == 0
        assert state.closed_executions == 0
        assert state.total_events == 0


class TestIncompleteExecution:
    """Tests for IncompleteExecution model."""

    def test_incomplete_execution_fields(self):
        """IncompleteExecution stores all expected fields."""
        from parrot.autonomous.ledger import IncompleteExecution

        now = datetime.now(timezone.utc)
        inc = IncompleteExecution(
            trace_id="t-abc",
            agent_id="bot-1",
            event_class="BeforeInvokeEvent",
            event_data={"task": "do stuff"},
            timestamp=now,
            last_seq=42,
        )
        assert inc.trace_id == "t-abc"
        assert inc.agent_id == "bot-1"
        assert inc.event_class == "BeforeInvokeEvent"
        assert inc.last_seq == 42


class TestLedgerDDL:
    """Tests for the LEDGER_DDL constant."""

    def test_ledger_ddl_contains_table(self):
        """LEDGER_DDL creates the harness_ledger table."""
        from parrot.autonomous.ledger import LEDGER_DDL

        assert "harness_ledger" in LEDGER_DDL
        assert "CREATE TABLE IF NOT EXISTS" in LEDGER_DDL

    def test_ledger_ddl_contains_indexes(self):
        """LEDGER_DDL creates the three expected indexes."""
        from parrot.autonomous.ledger import LEDGER_DDL

        assert "ix_ledger_agent_ts" in LEDGER_DDL
        assert "ix_ledger_trace" in LEDGER_DDL
        assert "ix_ledger_class" in LEDGER_DDL

    def test_ledger_ddl_uses_if_not_exists(self):
        """All DDL statements use IF NOT EXISTS for idempotence."""
        from parrot.autonomous.ledger import LEDGER_DDL

        count = LEDGER_DDL.count("IF NOT EXISTS")
        # 1 for the table + 3 for the indexes
        assert count >= 4
