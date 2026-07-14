---
type: Concept
title: physical_tables()
id: func:parrot.tools.dataset_manager.sources.resolver.physical_tables
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract physical table references from a SQL query using sqlglot.
---

# physical_tables

```python
def physical_tables(sql: str, dialect: str) -> set[str]
```

Extract physical table references from a SQL query using sqlglot.

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
