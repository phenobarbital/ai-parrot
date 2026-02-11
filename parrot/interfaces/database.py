"""DB (asyncdb) Extension.

Async database interface for relational databases using asyncdb.
Supports PostgreSQL (pg) and BigQuery with driver-aware SQL generation,
prepared statement caching, and object serialization (datamodel / pydantic).
"""
import warnings
from functools import lru_cache
from typing import Any, Dict, List, Optional

from asyncdb import AsyncDB
from navconfig.logging import logging


logger = logging.getLogger("DBInterface")


# ---------------------------------------------------------------------------
# SQL generation helpers (cacheable, pure functions)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=256)
def _build_insert_sql(schema: str, table: str, columns: tuple[str, ...]) -> str:
    """Build a parameterised INSERT statement."""
    qualified = f"{schema}.{table}" if schema else table
    cols = ", ".join(columns)
    placeholders = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
    return f"INSERT INTO {qualified} ({cols}) VALUES ({placeholders})"


@lru_cache(maxsize=256)
def _build_update_sql(
    schema: str,
    table: str,
    set_columns: tuple[str, ...],
    where_columns: tuple[str, ...],
) -> str:
    """Build a parameterised UPDATE statement."""
    qualified = f"{schema}.{table}" if schema else table
    idx = 1
    set_parts: list[str] = []
    for col in set_columns:
        set_parts.append(f"{col} = ${idx}")
        idx += 1
    where_parts: list[str] = []
    for col in where_columns:
        where_parts.append(f"{col} = ${idx}")
        idx += 1
    return (
        f"UPDATE {qualified} SET {', '.join(set_parts)} "
        f"WHERE {' AND '.join(where_parts)}"
    )


@lru_cache(maxsize=256)
def _build_delete_sql(
    schema: str,
    table: str,
    where_columns: tuple[str, ...],
) -> str:
    """Build a parameterised DELETE statement."""
    qualified = f"{schema}.{table}" if schema else table
    parts = [f"{col} = ${i}" for i, col in enumerate(where_columns, 1)]
    return f"DELETE FROM {qualified} WHERE {' AND '.join(parts)}"


@lru_cache(maxsize=256)
def _build_select_sql(
    schema: str,
    table: str,
    fields: tuple[str, ...],
    where_columns: tuple[str, ...],
) -> str:
    """Build a parameterised SELECT statement."""
    qualified = f"{schema}.{table}" if schema else table
    cols = ", ".join(fields) if fields else "*"
    parts = [f"{col} = ${i}" for i, col in enumerate(where_columns, 1)]
    where_clause = f" WHERE {' AND '.join(parts)}" if parts else ""
    return f"SELECT {cols} FROM {qualified}{where_clause}"


def _obj_to_dict(obj: Any) -> dict:
    """Convert a datamodel or pydantic object to a plain dict."""
    if isinstance(obj, dict):
        return obj
    # pydantic v2
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    # python-datamodel
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    # pydantic v1 fallback
    if hasattr(obj, "dict"):
        return obj.dict()
    raise TypeError(
        f"Cannot convert {type(obj).__name__} to dict. "
        "Expected a dict, pydantic BaseModel, or python-datamodel instance."
    )


class DBInterface:
    """Interface for relational database operations using AsyncDB.

    Provides high-level CRUD helpers that build parameterised SQL,
    handle object serialisation, and delegate execution to the asyncdb driver.
    """

    # -----------------------------------------------------------------
    # Driver factory
    # -----------------------------------------------------------------

    def get_driver(
        self,
        driver: str = "pg",
        dsn: str = None,
        params: dict = None,
        timeout: int = 60,
        **kwargs,
    ) -> AsyncDB:
        """Create an AsyncDB driver instance."""
        return AsyncDB(
            driver,
            dsn=dsn,
            params=params,
            timeout=timeout,
            **kwargs,
        )

    # Backward-compatible alias
    def get_database(
        self,
        driver: str = "pg",
        dsn: str = None,
        params: dict = None,
        timeout: int = 60,
        **kwargs,
    ) -> AsyncDB:
        """Deprecated – use ``get_driver`` instead."""
        warnings.warn(
            "get_database() is deprecated, use get_driver() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.get_driver(driver, dsn=dsn, params=params, timeout=timeout, **kwargs)

    # -----------------------------------------------------------------
    # Low-level execution
    # -----------------------------------------------------------------

    async def execute(
        self,
        sentence: str,
        *args,
        driver: str = "pg",
        dsn: str = None,
        **kwargs,
    ) -> Any:
        """Execute a raw SQL statement via the asyncdb driver.

        Args:
            sentence: SQL string to execute.
            *args: Positional parameters for the query.
            driver: asyncdb driver name (default ``'pg'``).
            dsn: Data-source name / connection string.
            **kwargs: Extra keyword arguments forwarded to the driver.

        Returns:
            Whatever the underlying driver ``execute()`` returns.
        """
        db = self.get_driver(driver, dsn=dsn)
        async with await db.connection() as conn:  # pylint: disable=E1101
            result = await conn.execute(sentence, *args, **kwargs)
            return result

    # -----------------------------------------------------------------
    # Prepared statements
    # -----------------------------------------------------------------

    async def prepared_statement(
        self,
        sentence: str,
        driver: str = "pg",
        dsn: str = None,
    ) -> Any:
        """Create a prepared statement on the underlying driver connection.

        For ``driver='pg'`` this calls ``conn.prepare(sentence)`` which
        returns ``(prepared_stmt, error)``.

        Args:
            sentence: SQL string to prepare.
            driver: asyncdb driver name.
            dsn: Data-source name.

        Returns:
            The prepared-statement object (or tuple) from the driver.
        """
        db = self.get_driver(driver, dsn=dsn)
        async with await db.connection() as conn:
            if hasattr(conn, "prepare"):
                return await conn.prepare(sentence)
            raise NotImplementedError(
                f"Driver '{driver}' does not support prepared statements."
            )

    # -----------------------------------------------------------------
    # DDL helpers
    # -----------------------------------------------------------------

    async def ensure_indexes(
        self,
        table: str,
        schema: str,
        fields: List[str],
        index_type: str = "btree",
        driver: str = "pg",
        dsn: str = None,
    ) -> str:
        """Create an index on *fields* if it does not already exist.

        For ``driver='pg'`` generates::

            CREATE INDEX IF NOT EXISTS idx_{schema}_{table}_{fields[0]}
            ON {schema}.{table} USING {index_type} (field1, field2, …)

        Args:
            table: Table name.
            schema: Schema name.
            fields: List of column names to index.
            index_type: Index method (default ``'btree'``).
            driver: asyncdb driver name.
            dsn: Data-source name.

        Returns:
            The DDL statement that was executed.
        """
        if not fields:
            raise ValueError("fields list must not be empty.")

        idx_name = f"idx_{schema}_{table}_{fields[0]}"
        qualified_table = f"{schema}.{table}" if schema else table
        columns = ", ".join(fields)

        if driver == "pg":
            ddl = (
                f"CREATE INDEX IF NOT EXISTS {idx_name} "
                f"ON {qualified_table} USING {index_type} ({columns})"
            )
        else:
            # Generic fallback (works for most SQL dialects)
            ddl = (
                f"CREATE INDEX IF NOT EXISTS {idx_name} "
                f"ON {qualified_table} ({columns})"
            )

        logger.debug("ensure_indexes: %s", ddl)
        await self.execute(ddl, driver=driver, dsn=dsn)
        return ddl

    # -----------------------------------------------------------------
    # CRUD operations
    # -----------------------------------------------------------------

    async def insert(
        self,
        table: str,
        schema: str,
        obj: Any,
        driver: str = "pg",
        dsn: str = None,
        **kwargs,
    ) -> Any:
        """Insert a single record.

        Converts *obj* (pydantic model, datamodel, or dict) to a dict
        and executes a parameterised ``INSERT`` statement.

        If the record already exists (unique violation) a warning is
        logged and ``None`` is returned.

        For ``driver='bigquery'`` the asyncdb driver's ``write()`` method
        is used instead of raw SQL.

        Args:
            table: Table name.
            schema: Schema name.
            obj: Data object to insert.
            driver: asyncdb driver name.
            dsn: Data-source name.
            **kwargs: Extra keyword arguments forwarded to the driver.

        Returns:
            Driver result on success, ``None`` on duplicate.
        """
        data = _obj_to_dict(obj)
        if not data:
            raise ValueError("Object yielded an empty dict – nothing to insert.")

        # BigQuery special path
        if driver == "bigquery":
            db = self.get_driver(driver, dsn=dsn)
            async with await db.connection() as conn:  # pylint: disable=E1101
                return await conn.write(
                    table=f"{schema}.{table}" if schema else table,
                    data=[data],
                    **kwargs,
                )

        columns = tuple(data.keys())
        values = list(data.values())
        sql = _build_insert_sql(schema, table, columns)

        logger.debug("insert: %s  values=%s", sql, values)

        try:
            return await self.execute(sql, *values, driver=driver, dsn=dsn)
        except Exception as exc:
            exc_str = str(exc).lower()
            if "unique" in exc_str or "duplicate" in exc_str or "already exists" in exc_str:
                logger.warning(
                    "Insert skipped – record already exists in %s.%s: %s",
                    schema, table, exc,
                )
                return None
            raise

    async def update(
        self,
        table: str,
        schema: str,
        obj: Any,
        unique_fields: List[str],
        driver: str = "pg",
        dsn: str = None,
    ) -> Any:
        """Update a record identified by *unique_fields*.

        The values for the ``WHERE`` clause are extracted from *obj*
        using *unique_fields*.  All remaining fields become the ``SET``
        clause.

        Args:
            table: Table name.
            schema: Schema name.
            obj: Data object with the new values.
            unique_fields: Column names that form the uniqueness criteria.
            driver: asyncdb driver name.
            dsn: Data-source name.

        Returns:
            Driver result.
        """
        data = _obj_to_dict(obj)
        if not data:
            raise ValueError("Object yielded an empty dict – nothing to update.")

        # Split data into SET columns and WHERE columns
        set_cols = [k for k in data if k not in unique_fields]
        if not set_cols:
            raise ValueError("No columns to update after excluding unique_fields.")

        where_cols = [k for k in unique_fields if k in data]
        if len(where_cols) != len(unique_fields):
            missing = set(unique_fields) - set(where_cols)
            raise ValueError(f"unique_fields {missing} not found in object.")

        sql = _build_update_sql(
            schema, table, tuple(set_cols), tuple(where_cols)
        )
        values = [data[c] for c in set_cols] + [data[c] for c in where_cols]

        logger.debug("update: %s  values=%s", sql, values)
        return await self.execute(sql, *values, driver=driver, dsn=dsn)

    async def delete(
        self,
        table: str,
        schema: str,
        obj: Any,
        unique_fields: List[str],
        driver: str = "pg",
        dsn: str = None,
    ) -> Any:
        """Delete a record identified by *unique_fields*.

        The ``WHERE`` values are extracted from *obj*.

        Args:
            table: Table name.
            schema: Schema name.
            obj: Data object containing the key values.
            unique_fields: Column names for the WHERE clause.
            driver: asyncdb driver name.
            dsn: Data-source name.

        Returns:
            Driver result.
        """
        data = _obj_to_dict(obj)

        where_cols = [k for k in unique_fields if k in data]
        if len(where_cols) != len(unique_fields):
            missing = set(unique_fields) - set(where_cols)
            raise ValueError(f"unique_fields {missing} not found in object.")

        sql = _build_delete_sql(schema, table, tuple(where_cols))
        values = [data[c] for c in where_cols]

        logger.debug("delete: %s  values=%s", sql, values)
        return await self.execute(sql, *values, driver=driver, dsn=dsn)

    async def filter(
        self,
        table: str,
        schema: str,
        conditions: Dict[str, Any],
        fields: Optional[List[str]] = None,
        driver: str = "pg",
        dsn: str = None,
    ) -> Optional[List[Any]]:
        """Select rows matching *conditions*.

        Args:
            table: Table name.
            schema: Schema name.
            conditions: ``{column: value}`` dict for the WHERE clause.
            fields: Columns to return (``None`` → ``*``).
            driver: asyncdb driver name.
            dsn: Data-source name.

        Returns:
            List of rows (asyncpg Records) or ``None``.
        """
        field_tuple = tuple(fields) if fields else ()
        where_cols = tuple(conditions.keys())
        sql = _build_select_sql(schema, table, field_tuple, where_cols)
        values = list(conditions.values())

        logger.debug("filter: %s  values=%s", sql, values)

        db = self.get_driver(driver, dsn=dsn)
        async with await db.connection() as conn:  # pylint: disable=E1101
            result = await conn.fetch_all(sql, *values)
            return result

    async def get(
        self,
        table: str,
        schema: str,
        conditions: Dict[str, Any],
        fields: Optional[List[str]] = None,
        driver: str = "pg",
        dsn: str = None,
    ) -> Optional[Any]:
        """Fetch a single row matching *conditions*.

        Args:
            table: Table name.
            schema: Schema name.
            conditions: ``{column: value}`` dict for the WHERE clause.
            fields: Columns to return (``None`` → ``*``).
            driver: asyncdb driver name.
            dsn: Data-source name.

        Returns:
            A single row (asyncpg Record) or ``None``.
        """
        field_tuple = tuple(fields) if fields else ()
        where_cols = tuple(conditions.keys())
        sql = _build_select_sql(schema, table, field_tuple, where_cols)
        values = list(conditions.values())

        logger.debug("get: %s  values=%s", sql, values)

        db = self.get_driver(driver, dsn=dsn)
        async with await db.connection() as conn:  # pylint: disable=E1101
            result = await conn.fetch_one(sql, *values)
            return result
