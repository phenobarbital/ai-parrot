"""Resolve a logging level from a name, a number, or an environment string.

Shared by the ``quiet_*`` helpers in :mod:`parrot.utils.faiss_logging` and
:mod:`parrot.utils.http_logging`, which all expose the same escape hatch: a
library's chatter is raised to WARNING by default, and an environment
variable puts it back (``"DEBUG"``, ``"INFO"``, or a numeric level).
"""

from __future__ import annotations

import logging

__all__ = ("resolve_log_level",)


def resolve_log_level(raw: str | None, default: int) -> int:
    """Resolve a level name (``"DEBUG"``) or numeric string to a level int.

    Args:
        raw: Level name, numeric string, ``None``, or an empty/blank string.
        default: Level returned when ``raw`` is missing, blank, or not a
            level Python's ``logging`` module recognises.

    Returns:
        The resolved integer logging level.
    """
    if raw is None or raw.strip() == "":
        return default
    token = raw.strip().upper()
    if token.isdigit():
        return int(token)
    resolved = logging.getLevelName(token)
    return resolved if isinstance(resolved, int) else default
