"""Quiet FAISS's own import-time boot chatter.

FAISS logs through its ``faiss.loader`` logger the first time ``import faiss``
runs in a process — probing the CPU instruction set and reporting which shared
library it loaded::

    [DEBUG] faiss.loader :: Environment variable FAISS_OPT_LEVEL is not set ...
    [INFO]  faiss.loader :: Loading faiss with AVX2 support.
    [INFO]  faiss.loader :: Could not load library with AVX2 support due to: ...
    [INFO]  faiss.loader :: Loading faiss.
    [INFO]  faiss.loader :: Successfully loaded faiss.

These are emitted once at first import and carry no actionable information for
AI-Parrot users. ``quiet_faiss_loader`` raises the ``faiss`` logger family to
WARNING so only genuine problems surface. Because Python loggers are singletons
by name, setting the level here persists even though FAISS creates the logger at
import time — call this BEFORE the first ``import faiss`` and the boot lines are
suppressed for the whole process.

Override via the ``FAISS_LOG_LEVEL`` environment variable (e.g. ``INFO`` to
restore the full boot chatter, ``DEBUG``, or a numeric level).
"""

from __future__ import annotations

import logging
import os

_FAISS_LOGGER_NAME = "faiss"


def quiet_faiss_loader() -> None:
    """Raise the ``faiss`` logger to WARNING (or ``FAISS_LOG_LEVEL``). Idempotent.

    Safe to call repeatedly and from multiple import sites — the first call
    before ``import faiss`` wins; later calls just re-assert the same level.
    """
    level = _resolve_level(os.environ.get("FAISS_LOG_LEVEL"), logging.WARNING)
    logging.getLogger(_FAISS_LOGGER_NAME).setLevel(level)


def _resolve_level(raw: str | None, default: int) -> int:
    """Resolve a level name (``"DEBUG"``) or numeric string to a logging level int."""
    if raw is None or raw.strip() == "":
        return default
    token = raw.strip().upper()
    if token.isdigit():
        return int(token)
    resolved = logging.getLevelName(token)
    return resolved if isinstance(resolved, int) else default
