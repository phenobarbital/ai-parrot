"""
Event bus infrastructure for AI-Parrot.

The bus core (facade, backends, converters, DLQ, ingress, subscribers) has
been extracted to the standalone ``navigator-eventbus`` package (FEAT-312,
FEAT-317). This package no longer re-exports ``EventBus``/``Event``/
``EventPriority``/``EventSubscription`` — import them directly from
``navigator_eventbus``::

    from navigator_eventbus import EventBus, Event, EventPriority, EventSubscription

The lifecycle machinery and typed events that remain local to ai-parrot
live under ``parrot.core.events.lifecycle``.
"""
