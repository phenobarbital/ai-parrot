"""Physical-Resource Resolver for FEAT-228 Data-Plane Authorization.

Pure function module that maps any :class:`~parrot.tools.dataset_manager.sources.base.DataSource`
to the set of physical resources (driver + tables / source identifiers) it
will actually touch when executed.

This is the anti-alias-spoofing boundary: authorization decisions are made on
*what the source physically accesses*, not on the LLM-chosen dataset name.

Architecture (Spec §2, Module 1):
- SQL sources: sqlglot parses the query and extracts physical table references,
  excluding CTE aliases.  A read-only gate rejects DML/DDL.
- TableSource: trivially extracts ``driver:table`` from instance attributes.
- QuerySlugSource: returns empty resources (slug-level grants handled separately).
- InMemorySource: returns empty resources (no driver round-trip).
- Opaque sources (Mongo, Iceberg, Delta, Airtable, Smartsheet): delegates to
  :mod:`parrot.tools.dataset_manager.sources.opaque`.

Usage::

    from parrot.tools.dataset_manager.sources.resolver import (
        resolve_physical_resources, physical_tables,
        PhysicalResources, ReadOnlyViolation,
    )

    resources = resolve_physical_resources(my_sql_source)
    # resources.driver = "bigquery"
    # resources.tables = {"bigquery:schema.table"}
"""
from __future__ import annotations

from typing import Optional

import sqlglot
from sqlglot import exp
from pydantic import BaseModel, Field


class ReadOnlyViolation(Exception):
    """Raised when a SQL statement is not read-only (DML/DDL detected).

    The read-only gate is enforced before any network round-trip so that
    mutation attempts are caught at parse time.
    """


class PhysicalResources(BaseModel):
    """Resolved physical resources for a DataSource.

    Attributes:
        driver: Canonical driver name (e.g. ``"bigquery"``, ``"pg"``).
        tables: Set of table resource strings in ``"driver:schema.table"``
            form, used as resource IDs in the PBAC engine
            (``table:<driver>:<schema>.<table>``).
        source_type: Non-SQL source type identifier (e.g. ``"mongo"``).
        source_id: Non-SQL source identifier (e.g. ``"finance_db.transactions"``).
    """

    driver: Optional[str] = None
    tables: set[str] = Field(default_factory=set)
    source_type: Optional[str] = None
    source_id: Optional[str] = None


# Allowed top-level AST node types for read-only queries.
_READ_ONLY_TYPES = (exp.Select, exp.Union, exp.Subquery, exp.With)


def physical_tables(sql: str, dialect: str) -> set[str]:
    """Extract physical table references from a SQL query using sqlglot.

    Parses the SQL with ``dialect`` and walks the AST looking for
    ``exp.Table`` nodes, excluding any names that are CTE aliases
    (because those are virtual, not physical tables).

    The read-only gate checks the top-level node type.  Any statement
    whose root is not ``SELECT``/``UNION``/``SUBQUERY``/``WITH`` raises
    :class:`ReadOnlyViolation`.

    Args:
        sql: SQL query string to analyse.
        dialect: sqlglot dialect name (e.g. ``"postgres"``, ``"bigquery"``).

    Returns:
        Set of physical table names in ``schema.table`` or ``table`` form.

    Raises:
        ReadOnlyViolation: If the statement is not a read-only query.
        sqlglot.errors.ParseError: If the SQL cannot be parsed.

    Examples::

        >>> physical_tables("SELECT * FROM sales.orders", "postgres")
        {'sales.orders'}
        >>> physical_tables("DROP TABLE x", "postgres")  # raises ReadOnlyViolation
    """
    tree = sqlglot.parse_one(sql, dialect=dialect)

    # Read-only gate
    if not isinstance(tree, _READ_ONLY_TYPES):
        raise ReadOnlyViolation(
            f"Statement type '{type(tree).__name__}' is not read-only; "
            "only SELECT/UNION/SUBQUERY/WITH are allowed"
        )

    # Collect CTE alias names so we can exclude them from physical tables.
    cte_names: set[str] = {c.alias_or_name for c in tree.find_all(exp.CTE)}

    tables: set[str] = set()
    for t in tree.find_all(exp.Table):
        if t.name in cte_names:
            continue
        # Build a qualified name: catalog.schema.table, schema.table, or table.
        parts = [p for p in (t.catalog, t.db, t.name) if p]
        tables.add(".".join(parts))

    return tables


def resolve_physical_resources(
    source: "DataSource",  # noqa: F821  (forward ref; avoid circular import)
) -> PhysicalResources:
    """Resolve a DataSource to the set of physical resources it will touch.

    Dispatches on the source type:
    - :class:`~parrot.tools.dataset_manager.sources.sql.SQLQuerySource`:
      sqlglot parse + table extraction.
    - :class:`~parrot.tools.dataset_manager.sources.table.TableSource`:
      trivial single-table extraction.
    - :class:`~parrot.tools.dataset_manager.sources.query_slug.QuerySlugSource`:
      returns empty (slug grants handled separately).
    - :class:`~parrot.tools.dataset_manager.sources.memory.InMemorySource`:
      returns empty (no driver round-trip).
    - All other sources: delegates to :mod:`.opaque` resolver.

    Args:
        source: Any :class:`~parrot.tools.dataset_manager.sources.base.DataSource`
            subclass.

    Returns:
        A :class:`PhysicalResources` describing what the source accesses.
    """
    from parrot.tools.dataset_manager.sources.sql import SQLQuerySource
    from parrot.tools.dataset_manager.sources.table import TableSource
    from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource
    from parrot.tools.dataset_manager.sources.memory import InMemorySource
    from parrot.tools.dataset_manager.sources.dialects import driver_to_dialect

    if isinstance(source, SQLQuerySource):
        driver = source.driver  # already normalised
        dialect = driver_to_dialect(driver)
        if dialect is None:
            # Unknown dialect — return driver only; caller decides fail-open/closed
            return PhysicalResources(driver=driver)
        tables = physical_tables(source.sql, dialect)
        return PhysicalResources(
            driver=driver,
            tables={f"{driver}:{t}" for t in tables},
        )

    if isinstance(source, TableSource):
        return PhysicalResources(
            driver=source.driver,
            tables={f"{source.driver}:{source.table}"},
        )

    if isinstance(source, QuerySlugSource):
        # Slug resources are declared at registration time; the guard checks
        # dataset-level grants for slugs via the existing L1 path.
        return PhysicalResources()

    if isinstance(source, InMemorySource):
        # In-memory DataFrames have no driver and no external data surface.
        return PhysicalResources()

    # Opaque sources (Mongo, Iceberg, Delta, Airtable, Smartsheet, etc.)
    try:
        from parrot.tools.dataset_manager.sources.opaque import resolve_opaque_source

        return resolve_opaque_source(source)
    except ImportError:
        return PhysicalResources()
