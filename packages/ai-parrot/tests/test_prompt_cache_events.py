"""Unit tests for PromptCacheAppliedEvent and PromptCacheSkippedEvent.

FEAT-181 — Provider-Agnostic Prompt Caching (TASK-1225).
"""
import pytest
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.events.client import (
    PromptCacheAppliedEvent,
    PromptCacheSkippedEvent,
)


class TestPromptCacheAppliedEvent:
    def test_creation(self):
        tc = TraceContext.new_root()
        evt = PromptCacheAppliedEvent(
            trace_context=tc,
            client_name="anthropic",
            model="claude-sonnet-4-20250514",
            blocks_marked=2,
            est_tokens=3000,
            segment_hashes=("abc123", "def456"),
            source_type="client",
            source_name="anthropic",
        )
        assert evt.client_name == "anthropic"
        assert evt.model == "claude-sonnet-4-20250514"
        assert evt.blocks_marked == 2
        assert evt.est_tokens == 3000
        assert len(evt.segment_hashes) == 2

    def test_defaults(self):
        tc = TraceContext.new_root()
        evt = PromptCacheAppliedEvent(trace_context=tc)
        assert evt.client_name == ""
        assert evt.model == ""
        assert evt.blocks_marked == 0
        assert evt.est_tokens == 0
        assert evt.segment_hashes == ()

    def test_serialization(self):
        tc = TraceContext.new_root()
        evt = PromptCacheAppliedEvent(
            trace_context=tc,
            client_name="anthropic",
            model="claude-sonnet-4-20250514",
            source_type="client",
            source_name="anthropic",
        )
        d = evt.to_dict()
        assert "client_name" in d
        assert d["event_class"] == "PromptCacheAppliedEvent"
        assert "segment_hashes" in d
        # to_dict converts tuple → list
        assert isinstance(d["segment_hashes"], list)

    def test_frozen(self):
        tc = TraceContext.new_root()
        evt = PromptCacheAppliedEvent(trace_context=tc)
        with pytest.raises(AttributeError):
            evt.blocks_marked = 5  # type: ignore[misc]

    def test_segment_hashes_tuple(self):
        tc = TraceContext.new_root()
        evt = PromptCacheAppliedEvent(
            trace_context=tc,
            segment_hashes=("sha256abc", "sha256def"),
        )
        assert isinstance(evt.segment_hashes, tuple)

    def test_to_dict_json_serializable(self):
        import json
        tc = TraceContext.new_root()
        evt = PromptCacheAppliedEvent(
            trace_context=tc,
            client_name="openai",
            model="gpt-4o",
            blocks_marked=0,
            est_tokens=1500,
            segment_hashes=("abc",),
        )
        # Should not raise
        json.dumps(evt.to_dict())

    def test_exported_from_package(self):
        from parrot.core.events.lifecycle.events import PromptCacheAppliedEvent as PCE
        assert PCE is PromptCacheAppliedEvent


class TestPromptCacheSkippedEvent:
    def test_creation_with_reasons(self):
        tc = TraceContext.new_root()
        for reason in ("below_threshold", "provider_unsupported", "feature_off", "no_segments"):
            evt = PromptCacheSkippedEvent(
                trace_context=tc,
                client_name="groq",
                model="llama-3",
                reason=reason,
                source_type="client",
                source_name="groq",
            )
            assert evt.reason == reason

    def test_defaults(self):
        tc = TraceContext.new_root()
        evt = PromptCacheSkippedEvent(trace_context=tc)
        assert evt.client_name == ""
        assert evt.model == ""
        assert evt.reason == ""

    def test_serialization(self):
        tc = TraceContext.new_root()
        evt = PromptCacheSkippedEvent(
            trace_context=tc,
            reason="below_threshold",
        )
        d = evt.to_dict()
        assert d["reason"] == "below_threshold"
        assert d["event_class"] == "PromptCacheSkippedEvent"

    def test_frozen(self):
        tc = TraceContext.new_root()
        evt = PromptCacheSkippedEvent(trace_context=tc)
        with pytest.raises(AttributeError):
            evt.reason = "changed"  # type: ignore[misc]

    def test_to_dict_json_serializable(self):
        import json
        tc = TraceContext.new_root()
        evt = PromptCacheSkippedEvent(
            trace_context=tc,
            client_name="groq",
            reason="provider_unsupported",
        )
        json.dumps(evt.to_dict())

    def test_exported_from_package(self):
        from parrot.core.events.lifecycle.events import PromptCacheSkippedEvent as PCSE
        assert PCSE is PromptCacheSkippedEvent
