"""YAML declarative events block parser and wiring helper.

FEAT-176 — Lifecycle Events System (TASK-1196).

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

import importlib
from typing import Any, Callable, Optional

from navconfig.logging import logging

from parrot.core.events.lifecycle.base import LifecycleEvent
from parrot.core.events.lifecycle.registry import EventRegistry
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

logger = logging.getLogger("parrot.core.events.lifecycle.yaml_loader")


# ---------------------------------------------------------------------------
# Event class name registry — maps YAML string names to actual event classes
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve(dotted: str) -> Any:
    """Resolve a ``'module.path:ObjectName'`` string to the named object.

    Args:
        dotted: Import path in ``module.path:ObjectName`` format.

    Returns:
        The resolved attribute from the named module.

    Raises:
        ValueError: When *dotted* does not contain a ``:`` separator.
        ImportError: When the module or attribute cannot be found.
    """
    if ":" not in dotted:
        raise ValueError(
            f"Bad dotted path {dotted!r}: expected 'module.path:ObjectName' format."
        )
    mod_path, name = dotted.split(":", 1)
    mod = importlib.import_module(mod_path)
    try:
        return getattr(mod, name)
    except AttributeError as exc:
        raise ImportError(
            f"Module {mod_path!r} has no attribute {name!r}."
        ) from exc


def _make_where(where_dict: dict) -> Callable[[Any], bool]:
    """Build a predicate function from a ``where:`` clause dict.

    Each key in *where_dict* is compared against the corresponding attribute
    of the event.  Values can be a list (any-match) or a scalar (exact-match).

    Example YAML::

        where:
          tool_name: [jira_create_issue, jira_update_issue]
          client_name: claude

    Args:
        where_dict: Mapping of ``field → value | [value1, value2, ...]``.

    Returns:
        Callable predicate that returns ``True`` when all conditions match.
    """
    def predicate(event: Any) -> bool:
        for field_name, allowed in where_dict.items():
            value = getattr(event, field_name, None)
            if isinstance(allowed, list):
                if value not in allowed:
                    return False
            else:
                if value != allowed:
                    return False
        return True
    return predicate


# ---------------------------------------------------------------------------
# Public wiring entry point
# ---------------------------------------------------------------------------

def wire_events(bot: Any, events_block: Optional[dict]) -> None:
    """Apply a parsed YAML ``events:`` block to the bot's event registry.

    Iterates over ``events_block["subscribers"]`` and wires each entry as
    either a handler callback (``handler:`` key) or an ``EventProvider``
    subclass (``provider:`` key) onto ``bot.events``.

    Args:
        bot: An ``AbstractBot`` instance that exposes ``bot.events`` (an
            ``EventRegistry``).  No-op if *bot* lacks the attribute.
        events_block: The parsed ``events:`` section from the agent YAML, or
            ``None`` / empty dict (no-op).

    Raises:
        ValueError: When a subscriber entry lacks both ``handler`` and
            ``provider`` keys, or when an event class name is unknown.
        ImportError: When a dotted-path resolution fails.
    """
    if not events_block:
        return

    if not hasattr(bot, "events"):
        logger.warning(
            "wire_events: bot %r has no 'events' attribute — skipping YAML event wiring.",
            getattr(bot, "name", repr(bot)),
        )
        return

    registry: EventRegistry = bot.events

    for sub in events_block.get("subscribers", []):
        if "handler" in sub:
            _wire_handler(registry, sub)
        elif "provider" in sub:
            _wire_provider(registry, sub)
        else:
            raise ValueError(
                f"Subscriber entry must have 'handler' or 'provider' key: {sub!r}"
            )


def _wire_handler(registry: EventRegistry, sub: dict) -> None:
    """Wire a single handler-form subscriber entry.

    Args:
        registry: The ``EventRegistry`` to register the callback on.
        sub: A subscriber dict with at minimum a ``handler`` key.

    Raises:
        ValueError: When an event class name in ``events:`` is unknown.
        ImportError: When the handler dotted-path cannot be resolved.
    """
    cb = _resolve(sub["handler"])
    raw_events = sub.get("events", [])
    if raw_events:
        try:
            evt_classes = [EVENT_CLASSES[n] for n in raw_events]
        except KeyError as exc:
            raise ValueError(
                f"Unknown event class name {exc} in subscriber 'events' list. "
                f"Known names: {sorted(EVENT_CLASSES)}."
            ) from exc
    else:
        # No filter → subscribe to all lifecycle events
        evt_classes = [LifecycleEvent]

    where_dict = sub.get("where")
    predicate = _make_where(where_dict) if where_dict else None
    forward_to_bus: bool = bool(sub.get("forward_to_bus", False))

    for ec in evt_classes:
        registry.subscribe(
            ec,
            cb,
            where=predicate,
            forward_to_bus=forward_to_bus,
        )

    logger.debug(
        "wire_events: wired handler %r for events %r",
        sub["handler"],
        [c.__name__ for c in evt_classes],
    )


def _wire_provider(registry: EventRegistry, sub: dict) -> None:
    """Wire a single provider-form subscriber entry.

    Args:
        registry: The ``EventRegistry`` to register the provider on.
        sub: A subscriber dict with at minimum a ``provider`` key.

    Raises:
        ImportError: When the provider dotted-path cannot be resolved.
    """
    provider_cls = _resolve(sub["provider"])
    config_kwargs: dict = sub.get("config", {}) or {}
    provider = provider_cls(**config_kwargs)
    registry.add_provider(provider)

    logger.debug("wire_events: wired provider %r", sub["provider"])
