"""Backward-compatible re-export of EventBus from the canonical location.

The EventBus implementation now lives in ``parrot.core.events``.
This module is kept for backward compatibility with existing code that
imports from ``parrot.autonomous.evb``.
"""
from parrot.core.events.evb import (  # noqa: F401
    Event,
    EventBus,
    EventPriority,
    EventSubscription,
)

__all__ = [
    "EventBus",
    "Event",
    "EventPriority",
    "EventSubscription",
]
