"""YAML declarative events block parser and wiring helper.

FEAT-176 — Lifecycle Events System (TASK-1196).

FEAT-317: the generic wiring engine (``wire_events``, dotted-path
resolution, ``where:`` predicates) was extracted to
``navigator_eventbus.lifecycle.yaml_loader`` (FEAT-313). This module now
retains only ai-parrot's event-name table and registers it with the
package's injectable ``register_event_names()`` registry.

Allows agent YAML definitions to declare lifecycle event subscribers inline::

    events:
      forward_to_global: false
      subscribers:
        - handler: mypackage.callbacks:on_tool_call
          events: [BeforeToolCallEvent, AfterToolCallEvent]
          where:
            tool_name: [jira_create_issue, jira_update_issue]
          forward_to_bus: false
        - provider: mypackage.providers:MyProvider
          config:
            endpoint: "https://hooks.example.com"
"""
from __future__ import annotations

from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.yaml_loader import (
    register_event_names,
    wire_events,
)

from parrot.core.events.lifecycle.events import (
    AgentInitializedEvent,
    AgentConfiguredEvent,
    ToolManagerReadyEvent,
    AgentStatusChangedEvent,
    BeforeInvokeEvent,
    AfterInvokeEvent,
    InvokeFailedEvent,
    BeforeClientCallEvent,
    AfterClientCallEvent,
    ClientCallFailedEvent,
    ClientStreamChunkEvent,
    BeforeToolCallEvent,
    AfterToolCallEvent,
    ToolCallFailedEvent,
    MessageAddedEvent,
)

__all__ = ["EVENT_CLASSES", "wire_events"]


# ---------------------------------------------------------------------------
# Event class name registry — maps YAML string names to ai-parrot's own
# event classes; registered with navigator_eventbus's injectable
# register_event_names() so the package's wire_events() engine can resolve
# them (FEAT-313 "each embedding application registers its own taxonomy").
# ---------------------------------------------------------------------------

EVENT_CLASSES: dict[str, type] = {
    cls.__name__: cls
    for cls in [
        # Agent lifecycle
        AgentInitializedEvent,
        AgentConfiguredEvent,
        ToolManagerReadyEvent,
        AgentStatusChangedEvent,
        # Invocation
        BeforeInvokeEvent,
        AfterInvokeEvent,
        InvokeFailedEvent,
        # Client
        BeforeClientCallEvent,
        AfterClientCallEvent,
        ClientCallFailedEvent,
        ClientStreamChunkEvent,
        # Tool
        BeforeToolCallEvent,
        AfterToolCallEvent,
        ToolCallFailedEvent,
        # Message
        MessageAddedEvent,
        # Base (wildcard subscription)
        LifecycleEvent,
    ]
}

register_event_names(EVENT_CLASSES)
