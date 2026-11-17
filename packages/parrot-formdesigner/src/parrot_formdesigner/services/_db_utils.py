"""Shared database utilities for parrot-formdesigner services."""

from __future__ import annotations

_UNIQUE_VIOLATION_CODE = "23505"


def is_unique_violation(exc: Exception) -> bool:
    """Return True when ``exc`` is a Postgres UNIQUE constraint violation.

    Works for asyncpg (``UniqueViolationError``), psycopg2/3, and drivers
    that wrap the original error — without importing driver-specific types.
    """
    if type(exc).__name__ == "UniqueViolationError":
        return True
    sqlstate = getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)
    if sqlstate == _UNIQUE_VIOLATION_CODE:
        return True
    text = str(exc).lower()
    return "duplicate key" in text or "unique constraint" in text


_UNDEFINED_TABLE_CODE = "42P01"


def is_undefined_table(exc: Exception) -> bool:
    """True when ``exc`` is a Postgres undefined-table error (driver-agnostic, FEAT-731).

    Mirrors :func:`is_unique_violation`: matches the asyncpg ``UndefinedTableError``
    type name, SQLSTATE ``42P01``, or the ``relation ... does not exist`` message.
    """
    if type(exc).__name__ == "UndefinedTableError":
        return True
    sqlstate = getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)
    if sqlstate == _UNDEFINED_TABLE_CODE:
        return True
    text = str(exc).lower()
    return "relation" in text and "does not exist" in text
