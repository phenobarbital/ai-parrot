"""Per-request context helpers for the Telegram integration.

Exposes a ContextVar holding the current Telegram chat id so tools
executed inside ``agent.ask()`` (e.g. ``HumanTool``) can discover
who to address without the LLM having to know raw chat ids.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional


current_telegram_chat_id: ContextVar[Optional[str]] = ContextVar(
    "current_telegram_chat_id", default=None
)


@contextmanager
def telegram_chat_scope(chat_id: int | str | None) -> Iterator[None]:
    """Set the current Telegram chat id for the duration of the block."""
    value = None if chat_id is None else str(chat_id)
    token = current_telegram_chat_id.set(value)
    try:
        yield
    finally:
        current_telegram_chat_id.reset(token)


def get_current_telegram_chat_id() -> Optional[str]:
    """Return the current Telegram chat id, or None if unset."""
    return current_telegram_chat_id.get()
