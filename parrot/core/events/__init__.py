"""
Event bus infrastructure for AI-Parrot.

Provides Redis-backed pub/sub with glob-pattern matching and event history.
This is the canonical location — imported by both ``parrot.autonomous`` and
``parrot.integrations``.

Public API::

    from parrot.core.events import EventBus, Event, EventPriority, EventSubscription
"""

from .evb import Event, EventBus, EventPriority, EventSubscription

__all__ = [
    "EventBus",
    "Event",
    "EventPriority",
    "EventSubscription",
]
