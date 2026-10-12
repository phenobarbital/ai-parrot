"""Real column shapes for tables the fake pools emulate.

A test double that accepts any column hides schema bugs. FEAT-302
shipped ``SELECT org_id, name FROM auth.organizations`` while the real
table has no ``name`` column, so every call failed in production with
``asyncpg.exceptions.UndefinedColumnError`` — and the fakes stayed
green. The fakes now validate the SELECT list of any query that reads
``auth.organizations`` against the real shape and raise like Postgres.

The column set below is the verified shape of ``auth.organizations``
in every environment (navigator_dev checked 2026-08-16).
``auth.organization_users`` (NAV-9522, the user → organization link)
was read from the production schema dump on 2026-10-12.
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

REAL_AUTH_ORGANIZATION_USERS_COLUMNS = frozenset({
    "user_id",
    "org_id",
    "properties",
    "created_at",
    "updated_at",
    "created_by",
})

# FROM target -> its real columns. A query is checked when its FROM target
# is one of these tables; a JOIN to another listed table adds its columns.
_REAL_COLUMNS = {
    "organizations": REAL_AUTH_ORGANIZATIONS_COLUMNS,
    "organization_users": REAL_AUTH_ORGANIZATION_USERS_COLUMNS,
}
_FROM_TABLE_RE = re.compile(r"\bFROM\s+auth\.(\w+)\b", re.IGNORECASE)
_JOIN_TABLE_RE = re.compile(r"\bJOIN\s+auth\.(\w+)\b", re.IGNORECASE)
_SELECT_LIST_RE = re.compile(
    r"\bSELECT\s+(?:DISTINCT\s+)?(.*?)\s+FROM\b", re.IGNORECASE | re.DOTALL
)


class FakeUndefinedColumnError(Exception):
    """Stands in for ``asyncpg.exceptions.UndefinedColumnError``."""


def assert_real_columns(sql: str) -> None:
    """Raise like Postgres when a query selects a column that does not exist.

    Only queries whose FROM target is ``auth.organizations`` or
    ``auth.organization_users`` are checked. A JOIN to the other table
    adds its columns to the allowed set.

    Args:
        sql: The SQL text the fake connection received.

    Raises:
        FakeUndefinedColumnError: A selected base column is not a real
            column of the tables the query reads.
    """
    source = _FROM_TABLE_RE.search(sql)
    if source is None or source.group(1).lower() not in _REAL_COLUMNS:
        return
    allowed = set(_REAL_COLUMNS[source.group(1).lower()])
    for joined in _JOIN_TABLE_RE.findall(sql):
        allowed |= _REAL_COLUMNS.get(joined.lower(), set())
    match = _SELECT_LIST_RE.search(sql)
    if match is None:
        return
    for expr in match.group(1).split(","):
        base = re.split(r"\s+AS\s+", expr.strip(), maxsplit=1, flags=re.IGNORECASE)[0]
        base = base.strip()
        if base == "*" or "(" in base:
            continue
        column = base.split(".")[-1].strip().strip('"')
        if column not in allowed:
            raise FakeUndefinedColumnError(f'column "{column}" does not exist')


# ---------------------------------------------------------------------------
# NAV-9522 — column REFERENCES (WHERE / JOIN), not only the SELECT list.
# ---------------------------------------------------------------------------
# The SELECT-list check above could not see the second shape of the same bug:
# ``WHERE client_id = $1`` against networkninja.regions / districts, which
# have no client_id column. Shapes below are from the production schema dump
# (bk_production_only_schema.sql, read 2026-10-12).

REAL_NETWORKNINJA_MARKETS_COLUMNS = frozenset({
    "market_id", "market_name", "district_id", "region_id", "client_id",
    "orgid", "is_active", "inserted_at",
})
REAL_NETWORKNINJA_DISTRICTS_COLUMNS = frozenset({
    "district_id", "district_name", "region_id", "orgid", "is_active",
    "inserted_at",
})
REAL_NETWORKNINJA_REGIONS_COLUMNS = frozenset({
    "region_id", "region_name", "orgid", "is_active", "inserted_at",
})

_REAL_TABLES = {
    "auth.organizations": REAL_AUTH_ORGANIZATIONS_COLUMNS,
    "auth.organization_users": REAL_AUTH_ORGANIZATION_USERS_COLUMNS,
    "networkninja.markets": REAL_NETWORKNINJA_MARKETS_COLUMNS,
    "networkninja.districts": REAL_NETWORKNINJA_DISTRICTS_COLUMNS,
    "networkninja.regions": REAL_NETWORKNINJA_REGIONS_COLUMNS,
}
_SQL_WORDS = {"on", "where", "join", "order", "group", "left", "inner", "limit"}
_TABLE_REF_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+(\w+\.\w+)(?:\s+(?:AS\s+)?(\w+))?", re.IGNORECASE
)
_QUALIFIED_RE = re.compile(r"\b(\w+)\.(\w+)\b")
_BARE_PREDICATE_RE = re.compile(
    r"(?<![\w.$])(\w+)\s*(?:=|<>|!=|<=|>=|<|>|\bIN\b|\bIS\b)", re.IGNORECASE
)


def assert_real_column_refs(sql: str) -> None:
    """Raise like Postgres when a query references a column a table lacks.

    Checks every ``alias.column`` whose alias names a known table, and —
    for a query that reads one known table without an alias — every bare
    column on the left of a WHERE/ON predicate. Unknown tables are skipped.

    Args:
        sql: The SQL text.

    Raises:
        FakeUndefinedColumnError: A referenced column does not exist.
    """
    aliases: dict[str, frozenset[str]] = {}
    known_unaliased: list[frozenset[str]] = []
    for table, alias in _TABLE_REF_RE.findall(sql):
        columns = _REAL_TABLES.get(table.lower())
        if columns is None:
            continue
        if alias and alias.lower() not in _SQL_WORDS:
            aliases[alias.lower()] = columns
        else:
            known_unaliased.append(columns)
    for qualifier, column in _QUALIFIED_RE.findall(sql):
        columns = aliases.get(qualifier.lower())
        if columns is not None and column.lower() not in columns:
            raise FakeUndefinedColumnError(f'column {qualifier}.{column} does not exist')
    if len(known_unaliased) == 1 and not aliases:
        predicates = re.split(r"\bWHERE\b", sql, maxsplit=1, flags=re.IGNORECASE)
        if len(predicates) == 2:
            for column in _BARE_PREDICATE_RE.findall(predicates[1]):
                if column.lower() in {"and", "or", "not", "true", "false", "null"}:
                    continue
                if column.lower() not in known_unaliased[0]:
                    raise FakeUndefinedColumnError(f'column "{column}" does not exist')
