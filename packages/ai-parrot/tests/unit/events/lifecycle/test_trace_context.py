"""Unit tests for TraceContext (TASK-1182, FEAT-176)."""
import json
import pytest
from dataclasses import FrozenInstanceError

from navigator_eventbus.lifecycle.trace import TraceContext


class TestTraceContext:
    """Tests for the TraceContext W3C Trace Context dataclass."""

    def test_new_root_format(self):
        """new_root() produces valid 32-char trace_id and 16-char span_id."""
        ctx = TraceContext.new_root()
        assert len(ctx.trace_id) == 32
        assert all(c in "0123456789abcdef" for c in ctx.trace_id)
        assert len(ctx.span_id) == 16
        assert all(c in "0123456789abcdef" for c in ctx.span_id)
        assert ctx.parent_span_id is None
        assert ctx.trace_flags == 1  # sampled by default

    def test_new_root_unique(self):
        """Two new_root() calls produce different trace_ids."""
        ctx1 = TraceContext.new_root()
        ctx2 = TraceContext.new_root()
        assert ctx1.trace_id != ctx2.trace_id
        assert ctx1.span_id != ctx2.span_id

    def test_child_preserves_trace_id(self):
        """child() preserves trace_id, generates fresh span_id, sets parent_span_id."""
        root = TraceContext.new_root()
        child = root.child()
        assert child.trace_id == root.trace_id
        assert child.span_id != root.span_id
        assert child.parent_span_id == root.span_id

    def test_child_preserves_flags_and_state(self):
        """child() preserves trace_flags and trace_state."""
        root = TraceContext.new_root()
        child = root.child()
        assert child.trace_flags == root.trace_flags
        assert child.trace_state == root.trace_state

    def test_traceparent_roundtrip(self):
        """from_traceparent_header(ctx.to_traceparent_header()) == ctx (structurally)."""
        ctx = TraceContext.new_root()
        header = ctx.to_traceparent_header()
        restored = TraceContext.from_traceparent_header(header)
        assert restored.trace_id == ctx.trace_id
        assert restored.span_id == ctx.span_id
        assert restored.trace_flags == ctx.trace_flags

    def test_traceparent_header_format(self):
        """to_traceparent_header() produces the correct 00-... format."""
        ctx = TraceContext.new_root()
        header = ctx.to_traceparent_header()
        parts = header.split("-")
        assert len(parts) == 4
        assert parts[0] == "00"
        assert len(parts[1]) == 32  # trace_id
        assert len(parts[2]) == 16  # span_id
        assert len(parts[3]) == 2   # flags

    @pytest.mark.parametrize("bad", [
        "",
        "00-tooshort-1234567890abcdef-01",
        "01-" + "a" * 32 + "-" + "b" * 16 + "-01",  # wrong version
        "not-a-header",
        "00-" + "g" * 32 + "-" + "a" * 16 + "-01",  # invalid hex in trace_id
        "00-" + "a" * 32 + "-" + "g" * 16 + "-01",  # invalid hex in span_id
        "00-" + "a" * 32 + "-" + "a" * 16 + "-gg",  # invalid hex in flags
        "00-" + "a" * 32 + "-" + "a" * 16 + "-01-extra",  # extra field
    ])
    def test_invalid_traceparent_raises(self, bad):
        """Invalid traceparent header raises ValueError."""
        with pytest.raises(ValueError):
            TraceContext.from_traceparent_header(bad)

    def test_frozen(self):
        """Mutation raises FrozenInstanceError."""
        ctx = TraceContext.new_root()
        with pytest.raises((FrozenInstanceError, TypeError)):
            ctx.trace_id = "deadbeef" * 4  # type: ignore[misc]

    def test_to_dict_is_json_serializable(self):
        """to_dict() output round-trips through json.dumps."""
        ctx = TraceContext.new_root()
        d = ctx.to_dict()
        assert json.dumps(d)  # should not raise

    def test_to_dict_fields(self):
        """to_dict() contains all five fields."""
        ctx = TraceContext.new_root()
        d = ctx.to_dict()
        assert set(d.keys()) == {"trace_id", "span_id", "trace_flags", "trace_state", "parent_span_id"}

    def test_from_dict_roundtrip(self):
        """from_dict(to_dict()) reconstructs an equal TraceContext."""
        ctx = TraceContext.new_root()
        restored = TraceContext.from_dict(ctx.to_dict())
        assert restored.trace_id == ctx.trace_id
        assert restored.span_id == ctx.span_id
        assert restored.trace_flags == ctx.trace_flags
        assert restored.trace_state == ctx.trace_state
        assert restored.parent_span_id == ctx.parent_span_id

    def test_child_dict_has_parent_span_id(self):
        """to_dict() of a child context includes parent_span_id."""
        root = TraceContext.new_root()
        child = root.child()
        d = child.to_dict()
        assert d["parent_span_id"] == root.span_id
