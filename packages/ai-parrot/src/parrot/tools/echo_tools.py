"""Lightweight diagnostic tools for smoke-testing the agent pipeline.

Provides a single ``get_current_datetime`` tool with zero external
dependencies — suitable for integration tests that verify tool-calling,
guardrails, and the full bot.ask() round-trip without touching any
production service.
"""
from datetime import datetime, timezone

from parrot.tools.decorators import tool


@tool
def get_current_datetime() -> str:
    """Return the current UTC date and time in ISO-8601 format.

    Use this tool whenever the user asks for the current date, time,
    or both.  The returned string follows the ``YYYY-MM-DDTHH:MM:SSZ``
    pattern.

    Returns:
        The current UTC timestamp, e.g. ``2026-08-07T22:30:00Z``.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
