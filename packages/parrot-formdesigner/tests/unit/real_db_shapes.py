"""Real column shapes for tables the fake pools emulate.

A test double that accepts any column hides schema bugs. FEAT-302
shipped ``SELECT org_id, name FROM auth.organizations`` while the real
table has no ``name`` column, so every call failed in production with
``asyncpg.exceptions.UndefinedColumnError`` — and the fakes stayed
green. The fakes now validate the SELECT list of any query that reads
``auth.organizations`` against the real shape and raise like Postgres.

The column set below is the verified shape of ``auth.organizations``
in every environment (navigator_dev checked 2026-08-16).
"""

from __future__ import annotations

import re

REAL_AUTH_ORGANIZATIONS_COLUMNS = frozenset({
    "org_id",
    "oid",
    "organization",
    "description",
    "attributes",
    "org_slug",
    "is_active",
    "created_at",
    "updated_at",
    "created_by",
})

_FROM_ORGANIZATIONS_RE = re.compile(
    r"\bFROM\s+auth\.organizations\b", re.IGNORECASE
)
_SELECT_LIST_RE = re.compile(
    r"\bSELECT\s+(?:DISTINCT\s+)?(.*?)\s+FROM\b", re.IGNORECASE | re.DOTALL
)


class FakeUndefinedColumnError(Exception):
    """Stands in for ``asyncpg.exceptions.UndefinedColumnError``."""


def assert_real_columns(sql: str) -> None:
    """Raise like Postgres when a query selects a column that does not exist.

    Only queries whose FROM target is ``auth.organizations`` are checked
    (single-table queries; the service has no joins against it).

    Args:
        sql: The SQL text the fake connection received.

    Raises:
        FakeUndefinedColumnError: A selected base column is not a real
            column of ``auth.organizations``.
    """
    if not _FROM_ORGANIZATIONS_RE.search(sql):
        return
    match = _SELECT_LIST_RE.search(sql)
    if match is None:
        return
    for expr in match.group(1).split(","):
        base = re.split(r"\s+AS\s+", expr.strip(), maxsplit=1, flags=re.IGNORECASE)[0]
        base = base.strip()
        if base == "*" or "(" in base:
            continue
        column = base.split(".")[-1].strip().strip('"')
        if column not in REAL_AUTH_ORGANIZATIONS_COLUMNS:
            raise FakeUndefinedColumnError(f'column "{column}" does not exist')
