"""Pure-function CRUD helpers for PostgresToolkit (FEAT-106).

This module provides:

* :data:`ColumnsKey` — hashable cache-key type for ``_build_pydantic_model``.
* :func:`_columns_key_from_metadata` — converts ``TableMetadata.columns``
  into a ``ColumnsKey`` suitable for use as an ``lru_cache`` argument.
* :func:`_build_pydantic_model` — ``lru_cache``-backed dynamic
  ``pydantic.BaseModel`` builder.  ``extra="forbid"`` ensures unknown
  fields surface as ``ValidationError`` rather than silently ignored.
* Five SQL template builders (pure functions, no I/O):
  - :func:`_build_insert_sql`
  - :func:`_build_upsert_sql`
  - :func:`_build_update_sql`
  - :func:`_build_delete_sql`
  - :func:`_build_select_sql`

All builders return ``(sql: str, param_order: list[str])`` where
``param_order`` matches the ``$N`` positional placeholder order used by
asyncpg.
"""
from __future__ import annotations

import functools
from typing import Any, FrozenSet, List, Optional, Tuple, Type, Union

from pydantic import BaseModel, ConfigDict, create_model

from datamodel.types import MODEL_TYPES

from parrot.bots.database.models import TableMetadata
from parrot.bots.database.toolkits.base import DatabaseToolkit


# ---------------------------------------------------------------------------
# ColumnsKey type alias
# ---------------------------------------------------------------------------

#: Hashable tuple used as the ``lru_cache`` key for ``_build_pydantic_model``.
#: Each element: ``(column_name, python_type, is_nullable, is_json)``.
ColumnsKey = Tuple[Tuple[str, type, bool, bool], ...]

#: PG type names that should be treated as JSON (accept ``dict`` or ``list``).
_JSON_TYPES: FrozenSet[str] = frozenset({"json", "jsonb", "hstore"})


# ---------------------------------------------------------------------------
# ColumnsKey helper
# ---------------------------------------------------------------------------

def _columns_key_from_metadata(meta: TableMetadata) -> ColumnsKey:
    """Build a hashable cache key from ``TableMetadata.columns``.

    Each tuple in the returned key captures the information needed to build
    a Pydantic field: ``(name, python_type, is_nullable, is_json)``.

    Args:
        meta: Table metadata whose ``columns`` list is converted.

    Returns:
        A ``ColumnsKey`` tuple suitable for :func:`_build_pydantic_model`.
    """
    items = []
    for col in meta.columns:
        name: str = col["name"]
        pg_type: str = (col.get("type") or "text").lower()
        py_type: type = MODEL_TYPES.get(pg_type, str)
        is_nullable: bool = bool(col.get("nullable", True))
        is_json: bool = pg_type in _JSON_TYPES
        items.append((name, py_type, is_nullable, is_json))
    return tuple(items)


# ---------------------------------------------------------------------------
# Dynamic Pydantic model builder (lru_cache'd)
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def _build_pydantic_model(
    model_name: str,
    columns_key: ColumnsKey,
) -> Type[BaseModel]:
    """Build (or return cached) a Pydantic model for a table's columns.

    All fields are ``Optional`` with default ``None`` — per-operation
    required-ness is enforced by the caller (insert / update / delete).
    ``extra="forbid"`` rejects unknown fields so incorrect LLM inputs
    surface as ``ValidationError`` rather than silently passing.

    The function is module-level (not a method) so ``functools.lru_cache``
    works without the ``self`` parameter.

    Args:
        model_name: Stable name for the generated model class, e.g.
            ``"auth_programs_model"``.
        columns_key: Hashable ``ColumnsKey`` produced by
            :func:`_columns_key_from_metadata`.

    Returns:
        A dynamically-created ``Type[BaseModel]`` with one optional field
        per column.

    Example::

        from parrot.bots.database.toolkits._crud import (
            _columns_key_from_metadata,
            _build_pydantic_model,
        )
        key = _columns_key_from_metadata(meta)
        Model = _build_pydantic_model("my_table_model", key)
        validated = Model(**data)
    """
    fields: dict[str, Any] = {}
    for name, py_type, _is_nullable, is_json in columns_key:
        if is_json:
            # JSON/JSONB: accept both dict and list payloads.
            annotation: type = Optional[Union[dict, list]]  # type: ignore[assignment]
        else:
            annotation = Optional[py_type]  # type: ignore[assignment]
        fields[name] = (annotation, None)

    return create_model(
        model_name,
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


# ---------------------------------------------------------------------------
# SQL template builders (pure functions)
# ---------------------------------------------------------------------------

def _build_insert_sql(
    schema: str,
    table: str,
    columns: List[str],
    returning: Optional[List[str]] = None,
    json_cols: FrozenSet[str] = frozenset(),
) -> Tuple[str, List[str]]:
    """Build a parameterized INSERT statement.

    Args:
        schema: Schema name (validated via :meth:`DatabaseToolkit._validate_identifier`).
        table: Table name (validated).
        columns: Ordered list of column names to insert.
        returning: Optional list of columns for the RETURNING clause.
        json_cols: Set of column names that hold JSON/JSONB values; these
            get a ``$N::text::jsonb`` cast.

    Returns:
        ``(sql, param_order)`` where ``param_order`` matches the ``$N``
        placeholder order.

    Raises:
        ValueError: If any identifier fails validation.
    """
    s = DatabaseToolkit._validate_identifier(schema)
    t = DatabaseToolkit._validate_identifier(table)
    cols = [DatabaseToolkit._validate_identifier(c) for c in columns]

    placeholders: List[str] = []
    for i, c in enumerate(cols, start=1):
        if c in json_cols:
            placeholders.append(f"${i}::text::jsonb")
        else:
            placeholders.append(f"${i}")

    col_list = ", ".join(f'"{c}"' for c in cols)
    vals = ", ".join(placeholders)
    sql = f'INSERT INTO "{s}"."{t}" ({col_list}) VALUES ({vals})'

    if returning:
        ret_cols = ", ".join(
            f'"{DatabaseToolkit._validate_identifier(r)}"' for r in returning
        )
        sql += f" RETURNING {ret_cols}"

    return sql, list(columns)


def _build_upsert_sql(
    schema: str,
    table: str,
    columns: List[str],
    conflict_cols: Optional[List[str]],
    update_cols: Optional[List[str]] = None,
    returning: Optional[List[str]] = None,
    json_cols: FrozenSet[str] = frozenset(),
) -> Tuple[str, List[str]]:
    """Build a parameterized INSERT … ON CONFLICT statement.

    Args:
        schema: Schema name.
        table: Table name.
        columns: Full list of columns to INSERT.
        conflict_cols: Columns defining the conflict target.  Must be
            non-empty; the caller (e.g. ``upsert_row``) defaults this to
            ``meta.primary_keys``.
        update_cols: Columns to update on conflict.  ``[]`` → ``DO NOTHING``.
            ``None`` → all columns not in ``conflict_cols``.
        returning: Optional RETURNING columns.
        json_cols: Column names carrying JSON/JSONB values (get
            ``$N::text::jsonb`` casts).

    Returns:
        ``(sql, param_order)`` — ``param_order`` is the INSERT column order.

    Raises:
        ValueError: If ``conflict_cols`` is empty/None or any identifier fails.
    """
    if not conflict_cols:
        raise ValueError(
            "conflict_cols must be non-empty; pass meta.primary_keys or an "
            "explicit list of columns that define the uniqueness constraint."
        )

    s = DatabaseToolkit._validate_identifier(schema)
    t = DatabaseToolkit._validate_identifier(table)
    cols = [DatabaseToolkit._validate_identifier(c) for c in columns]
    c_cols = [DatabaseToolkit._validate_identifier(c) for c in conflict_cols]

    # Build INSERT part (same as _build_insert_sql)
    placeholders: List[str] = []
    for i, c in enumerate(cols, start=1):
        if c in json_cols:
            placeholders.append(f"${i}::text::jsonb")
        else:
            placeholders.append(f"${i}")

    col_list = ", ".join(f'"{c}"' for c in cols)
    vals = ", ".join(placeholders)
    sql = f'INSERT INTO "{s}"."{t}" ({col_list}) VALUES ({vals})'

    # ON CONFLICT clause
    conflict_target = ", ".join(f'"{c}"' for c in c_cols)
    conflict_set = set(c_cols)

    if update_cols is None:
        # Default: update all non-conflict columns
        u_cols = [c for c in cols if c not in conflict_set]
    else:
        u_cols = [DatabaseToolkit._validate_identifier(c) for c in update_cols]

    if u_cols:
        set_clause = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in u_cols)
        sql += f" ON CONFLICT ({conflict_target}) DO UPDATE SET {set_clause}"
    else:
        sql += f" ON CONFLICT ({conflict_target}) DO NOTHING"

    if returning:
        ret_cols = ", ".join(
            f'"{DatabaseToolkit._validate_identifier(r)}"' for r in returning
        )
        sql += f" RETURNING {ret_cols}"

    return sql, list(columns)


def _build_update_sql(
    schema: str,
    table: str,
    set_columns: List[str],
    where_columns: List[str],
    returning: Optional[List[str]] = None,
    json_cols: FrozenSet[str] = frozenset(),
) -> Tuple[str, List[str]]:
    """Build a parameterized UPDATE statement.

    Args:
        schema: Schema name.
        table: Table name.
        set_columns: Columns in the SET clause (ordered).
        where_columns: Columns in the WHERE clause (ordered; ``AND``-joined).
        returning: Optional RETURNING columns.
        json_cols: Column names carrying JSON/JSONB values.

    Returns:
        ``(sql, param_order)`` where ``param_order = set_columns + where_columns``.

    Raises:
        ValueError: If ``where_columns`` is empty or any identifier fails.
    """
    if not where_columns:
        raise ValueError(
            "UPDATE requires at least one WHERE column to prevent full-table updates."
        )

    s = DatabaseToolkit._validate_identifier(schema)
    t = DatabaseToolkit._validate_identifier(table)
    s_cols = [DatabaseToolkit._validate_identifier(c) for c in set_columns]
    w_cols = [DatabaseToolkit._validate_identifier(c) for c in where_columns]

    set_parts: List[str] = []
    for i, c in enumerate(s_cols, start=1):
        if c in json_cols:
            set_parts.append(f'"{c}" = ${i}::text::jsonb')
        else:
            set_parts.append(f'"{c}" = ${i}')

    where_offset = len(s_cols) + 1
    where_parts: List[str] = []
    for i, c in enumerate(w_cols, start=where_offset):
        where_parts.append(f'"{c}" = ${i}')

    set_clause = ", ".join(set_parts)
    where_clause = " AND ".join(where_parts)
    sql = f'UPDATE "{s}"."{t}" SET {set_clause} WHERE {where_clause}'

    if returning:
        ret_cols = ", ".join(
            f'"{DatabaseToolkit._validate_identifier(r)}"' for r in returning
        )
        sql += f" RETURNING {ret_cols}"

    return sql, list(set_columns) + list(where_columns)


def _build_delete_sql(
    schema: str,
    table: str,
    where_columns: List[str],
    returning: Optional[List[str]] = None,
) -> Tuple[str, List[str]]:
    """Build a parameterized DELETE statement.

    Args:
        schema: Schema name.
        table: Table name.
        where_columns: Columns in the WHERE clause (``AND``-joined).
        returning: Optional RETURNING columns.

    Returns:
        ``(sql, param_order)`` where ``param_order = where_columns``.

    Raises:
        ValueError: If ``where_columns`` is empty or any identifier fails.
    """
    if not where_columns:
        raise ValueError(
            "DELETE requires at least one WHERE column to prevent full-table deletes."
        )

    s = DatabaseToolkit._validate_identifier(schema)
    t = DatabaseToolkit._validate_identifier(table)
    w_cols = [DatabaseToolkit._validate_identifier(c) for c in where_columns]

    where_parts = [f'"{c}" = ${i}' for i, c in enumerate(w_cols, start=1)]
    where_clause = " AND ".join(where_parts)
    sql = f'DELETE FROM "{s}"."{t}" WHERE {where_clause}'

    if returning:
        ret_cols = ", ".join(
            f'"{DatabaseToolkit._validate_identifier(r)}"' for r in returning
        )
        sql += f" RETURNING {ret_cols}"

    return sql, list(where_columns)


def _build_select_sql(
    schema: str,
    table: str,
    columns: Optional[List[str]] = None,
    where_columns: Optional[List[str]] = None,
    order_by: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> Tuple[str, List[str]]:
    """Build a parameterized SELECT statement.

    Args:
        schema: Schema name.
        table: Table name.
        columns: Columns to select; ``None`` → ``SELECT *``.
        where_columns: Columns for the WHERE clause (``AND``-joined).
            ``None`` or ``[]`` → no WHERE clause.
        order_by: ORDER BY expressions, e.g. ``["name ASC", "created_at DESC"]``.
            Only ``ASC`` and ``DESC`` direction keywords are accepted.
        limit: Maximum rows to return (inlined as an integer literal).

    Returns:
        ``(sql, param_order)`` where ``param_order = where_columns`` (or
        ``[]`` when no WHERE clause).

    Raises:
        ValueError: If any identifier fails or an unsupported ORDER BY
            direction is used.
    """
    s = DatabaseToolkit._validate_identifier(schema)
    t = DatabaseToolkit._validate_identifier(table)

    # SELECT clause
    if columns:
        sel = ", ".join(f'"{DatabaseToolkit._validate_identifier(c)}"' for c in columns)
    else:
        sel = "*"

    sql = f'SELECT {sel} FROM "{s}"."{t}"'

    # WHERE clause
    param_order: List[str] = []
    if where_columns:
        w_cols = [DatabaseToolkit._validate_identifier(c) for c in where_columns]
        where_parts = [f'"{c}" = ${i}' for i, c in enumerate(w_cols, start=1)]
        sql += " WHERE " + " AND ".join(where_parts)
        param_order = list(where_columns)

    # ORDER BY clause
    if order_by:
        order_parts: List[str] = []
        for entry in order_by:
            parts = entry.strip().split()
            col_name = DatabaseToolkit._validate_identifier(parts[0])
            if len(parts) >= 2:
                direction = parts[1].upper()
                if direction not in ("ASC", "DESC"):
                    raise ValueError(
                        f"Invalid ORDER BY direction {direction!r}; "
                        "only ASC and DESC are allowed."
                    )
                order_parts.append(f'"{col_name}" {direction}')
            else:
                order_parts.append(f'"{col_name}"')
        sql += " ORDER BY " + ", ".join(order_parts)

    # LIMIT clause
    if limit is not None:
        if not isinstance(limit, int) or limit < 0:
            raise ValueError(f"limit must be a non-negative integer, got {limit!r}")
        sql += f" LIMIT {limit}"

    return sql, param_order
