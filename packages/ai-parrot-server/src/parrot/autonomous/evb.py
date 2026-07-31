"""Backward-compatible re-export of EventBus from the canonical location.

FEAT-317: the EventBus implementation now lives in the standalone
``navigator-eventbus`` package. This module is kept for backward
compatibility with existing code that imports from
``parrot.autonomous.evb``.
"""
from navigator_eventbus.evb import (  # noqa: F401
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
