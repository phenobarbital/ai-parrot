"""Unit tests for LifecycleEvent base class (TASK-1183, FEAT-176)."""
import json
import pytest
from dataclasses import dataclass, FrozenInstanceError

from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.trace import TraceContext


@dataclass(frozen=True)
class _DummyEvent(LifecycleEvent):
    """Minimal concrete subclass for testing."""
    payload: str = ""


@dataclass(frozen=True)
class _BadEvent(LifecycleEvent):
    """Concrete subclass with a non-JSON-serializable field."""
    open_file: object = None   # non-JSON


@dataclass(frozen=True)
class _TupleEvent(LifecycleEvent):
    """Concrete subclass with a tuple field (for to_dict() tuple→list test)."""
    names: tuple = ()


class TestLifecycleEvent:
    """Tests for LifecycleEvent base class."""

    def test_frozen(self):
        """Mutating a frozen instance raises FrozenInstanceError."""
        evt = _DummyEvent(trace_context=TraceContext.new_root())
        with pytest.raises((FrozenInstanceError, TypeError)):
            evt.payload = "x"   # type: ignore[misc]

    def test_to_dict_roundtrips_json(self):
        """to_dict() returns a dict that round-trips through json.dumps."""
        evt = _DummyEvent(trace_context=TraceContext.new_root(), payload="hello")
        d = evt.to_dict()
        assert json.dumps(d)

    def test_to_dict_includes_event_class(self):
        """to_dict() adds 'event_class' key with the concrete class name."""
        evt = _DummyEvent(trace_context=TraceContext.new_root())
        assert evt.to_dict()["event_class"] == "_DummyEvent"

    def test_to_dict_trace_context_is_dict(self):
        """to_dict() serializes TraceContext to a nested dict."""
        ctx = TraceContext.new_root()
        evt = _DummyEvent(trace_context=ctx)
        d = evt.to_dict()
        assert isinstance(d["trace_context"], dict)
        assert d["trace_context"]["trace_id"] == ctx.trace_id

    def test_to_dict_timestamp_is_isoformat(self):
        """to_dict() serializes timestamp as ISO 8601 string."""
        evt = _DummyEvent(trace_context=TraceContext.new_root())
        d = evt.to_dict()
        assert isinstance(d["timestamp"], str)
        # Should parse without error
        from datetime import datetime
        datetime.fromisoformat(d["timestamp"])

    def test_to_dict_tuple_becomes_list(self):
        """to_dict() converts tuple fields to lists for JSON round-trip cleanliness."""
        evt = _TupleEvent(trace_context=TraceContext.new_root(), names=("a", "b"))
        d = evt.to_dict()
        assert d["names"] == ["a", "b"]
        assert isinstance(d["names"], list)

    def test_non_json_field_raises_typeerror(self, tmp_path):
        """A non-JSON-serializable field raises TypeError from to_dict()."""
        fh = open(tmp_path / "x.txt", "w")
        try:
            evt = _BadEvent(trace_context=TraceContext.new_root(), open_file=fh)
            with pytest.raises(TypeError, match="non-JSON-serializable"):
                evt.to_dict()
        finally:
            fh.close()

    def test_auto_event_id_generated(self):
        """event_id is auto-generated as a UUID4 string."""
        evt = _DummyEvent(trace_context=TraceContext.new_root())
        assert isinstance(evt.event_id, str)
        assert len(evt.event_id) == 36  # standard UUID4 format

    def test_two_events_have_different_ids(self):
        """Two events created back-to-back have different event_ids."""
        ctx = TraceContext.new_root()
        e1 = _DummyEvent(trace_context=ctx)
        e2 = _DummyEvent(trace_context=ctx)
        assert e1.event_id != e2.event_id

    def test_source_type_and_name_defaults(self):
        """source_type and source_name default to empty strings."""
        evt = _DummyEvent(trace_context=TraceContext.new_root())
        assert evt.source_type == ""
        assert evt.source_name == ""
