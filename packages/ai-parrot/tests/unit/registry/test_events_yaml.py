"""Unit tests for the YAML lifecycle events block parser and wiring helper.

FEAT-176 — Lifecycle Events System (TASK-1196).
"""
from __future__ import annotations

import sys
import types

import pytest

from parrot.core.events.lifecycle.yaml_loader import (
    EVENT_CLASSES,
    wire_events,
)
from navigator_eventbus.lifecycle.yaml_loader import (
    _make_where,
    _resolve,
)
from parrot.core.events.lifecycle.events import (
    BeforeToolCallEvent,
)
from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.trace import TraceContext


# ---------------------------------------------------------------------------
# _resolve tests
# ---------------------------------------------------------------------------

class TestResolve:
    """Tests for the dotted-path resolver."""

    def test_resolve_builtin_class(self) -> None:
        """Can resolve a class from an installed package."""
        cls = _resolve("parrot.core.events.lifecycle.events:BeforeToolCallEvent")
        assert cls is BeforeToolCallEvent

    def test_resolve_no_colon_raises(self) -> None:
        """Missing colon raises ValueError."""
        with pytest.raises(ValueError, match="expected 'module.path:ObjectName'"):
            _resolve("noseparatorhere")

    def test_resolve_missing_attribute_raises(self) -> None:
        """Existing module with missing attribute raises ImportError."""
        with pytest.raises(ImportError):
            _resolve("parrot.core.events.lifecycle.events:NonExistentClass")

    def test_resolve_missing_module_raises(self) -> None:
        """Non-existent module raises ModuleNotFoundError."""
        with pytest.raises(ModuleNotFoundError):
            _resolve("parrot.no.such.module:Something")


# ---------------------------------------------------------------------------
# _make_where tests
# ---------------------------------------------------------------------------

class TestMakeWhere:
    """Tests for the where-clause predicate builder."""

    def _make_event(self, tool_name: str) -> BeforeToolCallEvent:
        return BeforeToolCallEvent(
            trace_context=TraceContext.new_root(),
            tool_name=tool_name,
            tool_class="SomeTool",
            args_summary={},
            source_type="tool",
            source_name=tool_name,
        )

    def test_list_match_true(self) -> None:
        """Predicate returns True when field value is in the allowed list."""
        pred = _make_where({"tool_name": ["jira_create", "jira_update"]})
        evt = self._make_event("jira_create")
        assert pred(evt) is True

    def test_list_match_false(self) -> None:
        """Predicate returns False when field value is not in the allowed list."""
        pred = _make_where({"tool_name": ["jira_create", "jira_update"]})
        evt = self._make_event("github_push")
        assert pred(evt) is False

    def test_scalar_match_true(self) -> None:
        """Predicate returns True for exact scalar match."""
        pred = _make_where({"tool_name": "my_tool"})
        evt = self._make_event("my_tool")
        assert pred(evt) is True

    def test_scalar_match_false(self) -> None:
        """Predicate returns False for non-matching scalar."""
        pred = _make_where({"tool_name": "my_tool"})
        evt = self._make_event("other_tool")
        assert pred(evt) is False

    def test_missing_field_is_falsy(self) -> None:
        """Predicate returns False when the event lacks the field."""
        pred = _make_where({"nonexistent_field": "some_value"})
        evt = self._make_event("any_tool")
        assert pred(evt) is False


# ---------------------------------------------------------------------------
# wire_events tests
# ---------------------------------------------------------------------------

class _BotStub:
    """Minimal stub providing bot.events (EventRegistry)."""

    def __init__(self):
        self.events = EventRegistry(forward_to_global=False)
        self.name = "stub-bot"


def _register_stub_module(cb) -> str:
    """Register a callback as ``test_stub_<id>:cb`` in sys.modules.

    Returns:
        Dotted path string ``test_stub_<id>:cb``.
    """
    import uuid
    mod_name = f"test_stub_{uuid.uuid4().hex[:8]}"
    mod = types.ModuleType(mod_name)
    mod.cb = cb
    sys.modules[mod_name] = mod
    return f"{mod_name}:cb"


class TestWireEvents:
    """Tests for the wire_events() wiring helper."""

    def test_handler_form_registers_subscription(self) -> None:
        """handler: form creates exactly one subscription for one event class."""
        captured = []

        async def cb(e):
            captured.append(e)

        path = _register_stub_module(cb)
        bot = _BotStub()
        block = {
            "subscribers": [
                {
                    "handler": path,
                    "events": ["BeforeToolCallEvent"],
                }
            ]
        }
        wire_events(bot, block)
        assert len(bot.events._subscriptions) == 1
        sub = bot.events._subscriptions[0]
        assert sub.event_type is BeforeToolCallEvent

    def test_handler_no_events_defaults_to_lifecycle_event(self) -> None:
        """handler without 'events:' subscribes to all LifecycleEvents."""
        async def cb(e):
            pass

        path = _register_stub_module(cb)
        bot = _BotStub()
        block = {
            "subscribers": [
                {"handler": path}
            ]
        }
        wire_events(bot, block)
        assert len(bot.events._subscriptions) == 1
        assert bot.events._subscriptions[0].event_type is LifecycleEvent

    def test_handler_multiple_events_creates_multiple_subscriptions(self) -> None:
        """handler with multiple events: creates one subscription per class."""
        async def cb(e):
            pass

        path = _register_stub_module(cb)
        bot = _BotStub()
        block = {
            "subscribers": [
                {
                    "handler": path,
                    "events": ["BeforeToolCallEvent", "BeforeInvokeEvent"],
                }
            ]
        }
        wire_events(bot, block)
        assert len(bot.events._subscriptions) == 2

    def test_handler_where_clause_sets_predicate(self) -> None:
        """handler with 'where:' clause stores a non-None predicate."""
        async def cb(e):
            pass

        path = _register_stub_module(cb)
        bot = _BotStub()
        block = {
            "subscribers": [
                {
                    "handler": path,
                    "events": ["BeforeToolCallEvent"],
                    "where": {"tool_name": ["my_tool"]},
                }
            ]
        }
        wire_events(bot, block)
        sub = bot.events._subscriptions[0]
        assert sub.where is not None

    def test_handler_forward_to_bus_honored(self) -> None:
        """forward_to_bus: true is forwarded to the Subscription."""
        async def cb(e):
            pass

        path = _register_stub_module(cb)
        bot = _BotStub()
        block = {
            "subscribers": [
                {
                    "handler": path,
                    "events": ["BeforeToolCallEvent"],
                    "forward_to_bus": True,
                }
            ]
        }
        wire_events(bot, block)
        assert bot.events._subscriptions[0].forward_to_bus is True

    def test_provider_form_calls_add_provider(self) -> None:
        """provider: form calls registry.add_provider() with constructed instance."""
        from navigator_eventbus.lifecycle.provider import EventProvider

        class _MockProvider(EventProvider):
            def __init__(self, *, tag: str = ""):
                self.tag = tag

            def get_subscriptions(self):
                return []

        # Register in sys.modules
        import uuid
        mod_name = f"test_provider_{uuid.uuid4().hex[:8]}"
        mod = types.ModuleType(mod_name)
        mod.MockProvider = _MockProvider
        sys.modules[mod_name] = mod

        bot = _BotStub()
        block = {
            "subscribers": [
                {
                    "provider": f"{mod_name}:MockProvider",
                    "config": {"tag": "test-tag"},
                }
            ]
        }
        wire_events(bot, block)
        # add_provider() registers each of the provider's subscriptions
        # (MockProvider returns []) — no subscriptions but no error either
        # The key check: no exception was raised
        assert len(bot.events._subscriptions) == 0  # empty provider

    def test_missing_handler_and_provider_raises(self) -> None:
        """Subscriber with neither 'handler' nor 'provider' raises ValueError."""
        bot = _BotStub()
        block = {"subscribers": [{"unknown_key": "value"}]}
        with pytest.raises(ValueError, match="handler.*provider"):
            wire_events(bot, block)

    def test_unknown_event_class_raises(self) -> None:
        """Unknown event class name in 'events:' raises ValueError."""
        async def cb(e):
            pass

        path = _register_stub_module(cb)
        bot = _BotStub()
        block = {
            "subscribers": [
                {
                    "handler": path,
                    "events": ["NoSuchEventClass"],
                }
            ]
        }
        with pytest.raises(ValueError, match="Unknown event class"):
            wire_events(bot, block)

    def test_empty_block_is_noop(self) -> None:
        """wire_events with None or empty dict is a no-op."""
        bot = _BotStub()
        wire_events(bot, None)
        wire_events(bot, {})
        assert len(bot.events._subscriptions) == 0

    def test_event_classes_registry_populated(self) -> None:
        """EVENT_CLASSES includes all expected event names."""
        expected = {
            "AgentInitializedEvent", "AgentConfiguredEvent",
            "ToolManagerReadyEvent", "AgentStatusChangedEvent",
            "BeforeInvokeEvent", "AfterInvokeEvent", "InvokeFailedEvent",
            "BeforeClientCallEvent", "AfterClientCallEvent",
            "ClientCallFailedEvent", "ClientStreamChunkEvent",
            "BeforeToolCallEvent", "AfterToolCallEvent", "ToolCallFailedEvent",
            "MessageAddedEvent",
        }
        for name in expected:
            assert name in EVENT_CLASSES, f"Missing: {name!r}"
