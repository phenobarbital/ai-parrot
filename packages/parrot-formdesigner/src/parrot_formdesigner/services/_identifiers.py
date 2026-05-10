"""Postgres identifier validation helpers.

Identifiers (schema, table, tenant) cannot be parameterised via
``$1``/``$2`` placeholders, so they are interpolated into SQL strings.
To stay safe, every identifier that reaches the SQL templates MUST be
validated with :func:`validate_identifier` first — anything that does
not match the strict whitelist regex is rejected with ``ValueError``.

The accepted shape mirrors a conservative subset of unquoted Postgres
identifiers: a leading letter or underscore followed by up to 62
letters/digits/underscores. This is more restrictive than Postgres
itself (which allows quoted identifiers with arbitrary characters) but
removes the entire class of injection bugs at the source.
"""

from __future__ import annotations

import re

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def validate_identifier(value: str, *, kind: str = "identifier") -> str:
    """Return ``value`` if it is a safe Postgres identifier.

    Args:
        value: Candidate identifier (schema, table, tenant slug, etc.).
        kind: Human-readable label used in the error message.

    Returns:
        The validated identifier (unchanged).

    Raises:
        ValueError: If ``value`` is not a string matching the whitelist.
    """
    if not isinstance(value, str) or not _IDENTIFIER_RE.match(value):
        raise ValueError(
            f"Invalid {kind}: {value!r}. Must match {_IDENTIFIER_RE.pattern}."
        )
    return value


def qualified_table(schema: str, table: str) -> str:
    """Return ``"<schema>"."<table>"`` after validating both identifiers.

    Args:
        schema: Postgres schema name.
        table: Table name within that schema.

    Returns:
        A double-quoted, dot-qualified table reference safe to interpolate.
    """
    validate_identifier(schema, kind="schema")
    validate_identifier(table, kind="table")
    return f'"{schema}"."{table}"'
