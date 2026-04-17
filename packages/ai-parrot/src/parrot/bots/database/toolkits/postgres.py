"""PostgresToolkit — PostgreSQL-specific overrides of ``SQLToolkit``.

Provides PG-specific EXPLAIN format, ``pg_class``/``pg_namespace``
introspection, column comments via ``col_description()``,
``postgresql+asyncpg://`` DSN mapping, and full first-class CRUD tools:
``insert_row``, ``upsert_row``, ``update_row``, ``delete_row``,
``select_rows``.

Write tools are hidden from the LLM when ``read_only=True`` (the default)
by extending ``exclude_tools`` before ``AbstractToolkit._generate_tools()``
runs.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import (
    Any, AsyncIterator, Dict, FrozenSet, List, Optional, Type,
)

from pydantic import BaseModel, ValidationError

from ..models import TableMetadata
from .sql import SQLToolkit
from . import _crud


class PostgresToolkit(SQLToolkit):
    """PostgreSQL-specific toolkit with first-class CRUD tools.

    Overrides dialect hooks for PostgreSQL's richer introspection and
    EXPLAIN output.  When ``read_only=False``, five LLM-callable tools are
    exposed: ``db_insert_row``, ``db_upsert_row``, ``db_update_row``,
    ``db_delete_row``, and ``db_select_rows``.

    All write tools enforce a table whitelist (``self.tables``), validate
    input via a per-table dynamic Pydantic model, and cache parameterized
    SQL templates per instance.
    """

    def __init__(
        self,
        dsn: str,
        allowed_schemas: Optional[List[str]] = None,
        primary_schema: Optional[str] = None,
        tables: Optional[List[str]] = None,
        read_only: bool = True,
        backend: str = "asyncdb",
        use_pool: bool = False,
        pool_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        # --- CRUD instance state (before super().__init__ so exclude_tools is
        #     set before AbstractToolkit._generate_tools() runs) ---
        self._prepared_cache: Dict[str, tuple[str, List[str]]] = {}
        self._json_cols_cache: Dict[str, FrozenSet[str]] = {}
        self._in_transaction: bool = False

        # Gate write tools when read_only=True.
        # CRITICAL: must happen BEFORE super().__init__ (which calls
        # AbstractToolkit._generate_tools via chain).
        extra_excludes: tuple[str, ...] = ()
        if read_only:
            extra_excludes = ("insert_row", "upsert_row", "update_row", "delete_row")

        # Merge precedence:
        #   1. Any subclass pre-set instance exclude_tools (e.g. NavigatorToolkit)
        #   2. SQLToolkit class-level exclude_tools baseline
        #   3. read_only write-tool gates added here
        # Using `vars(self)` avoids picking up class-level attrs from the MRO
        # so we only extend a subclass's explicit pre-init assignment.
        subclass_excludes: tuple[str, ...] = vars(self).get("exclude_tools", ())
        base: tuple[str, ...] = subclass_excludes or tuple(SQLToolkit.exclude_tools)
        self.exclude_tools = base + extra_excludes

        super().__init__(
            dsn=dsn,
            allowed_schemas=allowed_schemas,
            primary_schema=primary_schema,
            tables=tables,
            read_only=read_only,
            backend=backend,
            database_type="postgresql",
            use_pool=use_pool,
            pool_params=pool_params,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Dialect hooks
    # ------------------------------------------------------------------

    def _get_explain_prefix(self) -> str:
        return "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)"

    def _get_information_schema_query(
        self,
        search_term: str,
        schemas: List[str],
    ) -> tuple[str, Dict[str, Any]]:
        """Use ``pg_class``/``pg_namespace`` joins for comment support."""
        sql = """
            SELECT DISTINCT
                ist.table_schema,
                ist.table_name,
                ist.table_type,
                obj_description(pgc.oid) AS comment
            FROM information_schema.tables ist
            LEFT JOIN pg_namespace pgn ON pgn.nspname = ist.table_schema
            LEFT JOIN pg_class pgc ON pgc.relname = ist.table_name
                AND pgc.relnamespace = pgn.oid
            WHERE ist.table_schema = ANY(:schemas)
            AND (
                ist.table_name ILIKE :term
                OR (ist.table_schema || '.' || ist.table_name) ILIKE :term
            )
            AND ist.table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY ist.table_name
            LIMIT :limit
        """
        return sql, {
            "schemas": schemas,
            "term": f"%{search_term}%",
            "limit": 20,
        }

    def _get_columns_query(
        self, schema: str, table: str
    ) -> tuple[str, Dict[str, Any]]:
        """Include ``col_description()`` for column comments."""
        sql = """
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                c.ordinal_position,
                col_description(
                    (SELECT oid FROM pg_class WHERE relname = :table
                     AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = :schema)),
                    c.ordinal_position
                ) AS column_comment
            FROM information_schema.columns c
            WHERE c.table_schema = :schema AND c.table_name = :table
            ORDER BY c.ordinal_position
        """
        return sql, {"schema": schema, "table": table}

    def _build_sqlalchemy_dsn(self, raw_dsn: str) -> str:
        """Ensure ``postgresql+asyncpg://`` prefix."""
        if raw_dsn.startswith("postgresql://"):
            return raw_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
        if raw_dsn.startswith("postgres://"):
            return raw_dsn.replace("postgres://", "postgresql+asyncpg://", 1)
        return raw_dsn

    def _get_asyncdb_driver(self) -> str:
        return "pg"

    # ------------------------------------------------------------------
    # CRUD private helpers
    # ------------------------------------------------------------------

    def _resolve_table(self, table: str) -> tuple[str, str, TableMetadata]:
        """Parse *table* and look up its metadata.

        Accepts ``"schema.table"`` or ``"table"`` (uses ``self.primary_schema``).
        Enforces the ``self.tables`` whitelist.

        Args:
            table: ``"schema.table"`` or bare table name.

        Returns:
            ``(schema, table_name, metadata)`` triple.

        Raises:
            ValueError: If ``schema.table`` is not in ``self.tables``.
            RuntimeError: If metadata is not available (not connected).
        """
        # Parse schema/table
        if "." in table:
            parts = table.split(".", 1)
            schema = parts[0].strip().strip('"').lower()
            table_name = parts[1].strip().strip('"').lower()
        else:
            schema = (self.primary_schema or "public").lower()
            table_name = table.strip().strip('"').lower()

        full = f"{schema}.{table_name}"

        # Whitelist check
        if self.tables:
            whitelist = {
                entry.lower().replace('"', '').replace(' ', '')
                for entry in self.tables
            }
            if full not in whitelist:
                raise ValueError(
                    f"Table {full!r} is not in the allowed table list. "
                    f"Allowed: {sorted(whitelist)}"
                )

        # Metadata lookup (synchronous — metadata should be warm after start())
        meta: Optional[TableMetadata] = None
        if self.cache_partition and hasattr(self.cache_partition, "schema_cache"):
            sc = self.cache_partition.schema_cache.get(schema)
            if sc and table_name in sc.tables:
                meta = sc.tables[table_name]

        if meta is None:
            # Build a minimal stub for cases where cache is not warm
            # (unit tests that mock _resolve_table can bypass this path)
            raise RuntimeError(
                f"No cached metadata for {full!r}. "
                "Call await toolkit.start() first to warm the metadata cache."
            )

        return schema, table_name, meta

    def _json_cols_for(self, meta: TableMetadata) -> FrozenSet[str]:
        """Return the set of JSON/JSONB column names for *meta*, cached."""
        key = f"{meta.schema}.{meta.tablename}"
        cached = self._json_cols_cache.get(key)
        if cached is not None:
            return cached
        cols: FrozenSet[str] = frozenset(
            c["name"]
            for c in meta.columns
            if (c.get("type") or "").lower() in {"json", "jsonb", "hstore"}
        )
        self._json_cols_cache[key] = cols
        return cols

    def _get_or_build_pydantic_model(self, meta: TableMetadata) -> Type[BaseModel]:
        """Return (or build) the dynamic Pydantic model for *meta*."""
        model_name = f"{meta.schema}_{meta.tablename}_model"
        key = _crud._columns_key_from_metadata(meta)
        return _crud._build_pydantic_model(model_name, key)

    def _make_template_key(
        self,
        op: str,
        schema: str,
        table: str,
        **kwargs: Any,
    ) -> str:
        """Build a deterministic string key for the prepared-statement cache."""
        parts = [f"{op}|{schema}|{table}"]
        for k, v in sorted(kwargs.items()):
            if v is None:
                parts.append(f"{k}=()")
            elif isinstance(v, (list, tuple)):
                parts.append(f"{k}={tuple(v)!r}")
            else:
                parts.append(f"{k}={v!r}")
        return "|".join(parts)

    def _get_or_build_template(
        self,
        op: str,
        schema: str,
        table: str,
        meta: TableMetadata,
        **kwargs: Any,
    ) -> tuple[str, List[str]]:
        """Return cached SQL template + param_order for *op* on *schema.table*.

        Results are stored as ``(sql, param_order)`` tuples so that repeated
        calls for the same operation shape short-circuit the builder entirely.
        The builder is only invoked on a cache miss.
        """
        cache_key = self._make_template_key(op, schema, table, **kwargs)

        cached = self._prepared_cache.get(cache_key)
        if cached is not None:
            self.logger.debug("Template cache hit: %s", cache_key)
            return cached

        self.logger.debug("Template cache miss: %s", cache_key)
        json_cols = self._json_cols_for(meta)

        if op == "insert":
            columns = kwargs.get("columns", [])
            returning = kwargs.get("returning")
            result = _crud._build_insert_sql(
                schema, table, columns,
                returning=returning,
                json_cols=json_cols,
            )
        elif op == "upsert":
            columns = kwargs.get("columns", [])
            conflict_cols = kwargs.get("conflict_cols")
            update_cols = kwargs.get("update_cols")
            returning = kwargs.get("returning")
            result = _crud._build_upsert_sql(
                schema, table, columns,
                conflict_cols=conflict_cols,
                update_cols=update_cols,
                returning=returning,
                json_cols=json_cols,
            )
        elif op == "update":
            set_columns = kwargs.get("set_columns", [])
            where_columns = kwargs.get("where_columns", [])
            returning = kwargs.get("returning")
            result = _crud._build_update_sql(
                schema, table,
                set_columns=set_columns,
                where_columns=where_columns,
                returning=returning,
                json_cols=json_cols,
            )
        elif op == "delete":
            where_columns = kwargs.get("where_columns", [])
            returning = kwargs.get("returning")
            result = _crud._build_delete_sql(
                schema, table,
                where_columns=where_columns,
                returning=returning,
            )
        elif op == "select":
            columns = kwargs.get("columns")
            where_columns = kwargs.get("where_columns")
            order_by = kwargs.get("order_by")
            limit = kwargs.get("limit")
            result = _crud._build_select_sql(
                schema, table,
                columns=columns,
                where_columns=where_columns,
                order_by=order_by,
                limit=limit,
            )
        else:
            raise ValueError(f"Unknown CRUD operation: {op!r}")

        self._prepared_cache[cache_key] = result
        return result

    def _prepare_args(
        self,
        data: Dict[str, Any],
        param_order: List[str],
        json_cols: FrozenSet[str],
    ) -> tuple[Any, ...]:
        """Build positional args tuple from *data* following *param_order*.

        JSON/JSONB column values are ``json.dumps``-serialized.
        """
        args = []
        for col in param_order:
            value = data.get(col)
            if value is not None and col in json_cols:
                value = json.dumps(value)
            args.append(value)
        return tuple(args)

    # ------------------------------------------------------------------
    # CRUD tool methods
    # ------------------------------------------------------------------

    async def insert_row(
        self,
        table: str,
        data: Dict[str, Any],
        returning: Optional[List[str]] = None,
        conn: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Insert a single row into *table*.

        Validates *data* against the table's dynamic Pydantic model
        (``extra="forbid"`` — unknown fields raise ``ValidationError``),
        builds and caches the INSERT SQL, then executes via asyncdb.

        Args:
            table: Target table as ``"schema.table"`` or bare name (uses
                ``primary_schema``).
            data: Column-value mapping.  Unknown keys are rejected.
            returning: Optional list of columns to RETURN.  When ``None``
                only a ``{"status": "ok"}`` dict is returned.
            conn: Optional existing transaction connection.  When provided,
                the CRUD method reuses it instead of acquiring a new one.

        Returns:
            The RETURNING row as a dict, or ``{"status": "ok"}`` when no
            RETURNING clause was requested.

        Raises:
            ValueError: Table not in whitelist.
            pydantic.ValidationError: Unknown or invalid field in *data*.
        """
        schema, table_name, meta = self._resolve_table(table)
        Model = self._get_or_build_pydantic_model(meta)
        validated = Model(**data).model_dump(exclude_none=True)

        columns = list(validated.keys())
        sql, param_order = self._get_or_build_template(
            "insert", schema, table_name, meta,
            columns=tuple(columns),
            returning=tuple(returning) if returning else None,
        )
        json_cols = self._json_cols_for(meta)
        args = self._prepare_args(validated, param_order, json_cols)

        return await self._execute_crud(sql, args, returning, conn, single_row=True)

    async def upsert_row(
        self,
        table: str,
        data: Dict[str, Any],
        conflict_cols: Optional[List[str]] = None,
        update_cols: Optional[List[str]] = None,
        returning: Optional[List[str]] = None,
        conn: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Upsert a single row into *table* using ``ON CONFLICT``.

        Defaults ``conflict_cols`` to ``meta.primary_keys`` when ``None``.
        Defaults ``update_cols`` to all non-conflict data keys when ``None``.

        When ``returning`` is provided but the ``DO UPDATE`` fires against
        an identical row (PG RETURNING yields 0 rows), a follow-up SELECT
        using ``conflict_cols`` is performed to return the existing row.

        Args:
            table: Target table.
            data: Column-value mapping.
            conflict_cols: Conflict target columns.  Defaults to PK columns.
            update_cols: Columns to update on conflict.  ``[]`` = DO NOTHING.
            returning: Optional RETURNING columns.
            conn: Optional existing transaction connection.

        Returns:
            The upserted / existing row as dict, or ``{"status": "ok"}``.

        Raises:
            ValueError: Table not in whitelist or conflict_cols is empty.
            pydantic.ValidationError: Invalid field in *data*.
        """
        schema, table_name, meta = self._resolve_table(table)
        Model = self._get_or_build_pydantic_model(meta)
        validated = Model(**data).model_dump(exclude_none=True)

        effective_conflict = conflict_cols or meta.primary_keys
        if not effective_conflict:
            raise ValueError(
                f"Cannot upsert into {table!r}: no conflict_cols provided "
                "and the table has no primary_keys in metadata."
            )

        columns = list(validated.keys())
        effective_update = update_cols
        if effective_update is None:
            conflict_set = set(effective_conflict)
            effective_update = [c for c in columns if c not in conflict_set]

        sql, param_order = self._get_or_build_template(
            "upsert", schema, table_name, meta,
            columns=tuple(columns),
            conflict_cols=tuple(effective_conflict),
            update_cols=tuple(effective_update),
            returning=tuple(returning) if returning else None,
        )
        json_cols = self._json_cols_for(meta)
        args = self._prepare_args(validated, param_order, json_cols)

        result = await self._execute_crud(sql, args, returning, conn, single_row=True)

        # Idempotency: if RETURNING was requested but we got empty dict back
        # (DO UPDATE fired on identical row with no actual change), perform
        # a follow-up SELECT using conflict_cols.
        if returning and not result:
            where = {c: validated[c] for c in effective_conflict if c in validated}
            if where:
                fallback_sql, fallback_params = self._get_or_build_template(
                    "select", schema, table_name, meta,
                    columns=tuple(returning),
                    where_columns=tuple(where.keys()),
                    order_by=None,
                    limit=1,
                )
                fallback_args = self._prepare_args(where, list(where.keys()), frozenset())
                rows = await self._execute_crud(
                    fallback_sql, fallback_args, returning, conn, single_row=False
                )
                if rows and isinstance(rows, list) and rows:
                    return rows[0]

        return result

    async def update_row(
        self,
        table: str,
        data: Dict[str, Any],
        where: Dict[str, Any],
        returning: Optional[List[str]] = None,
        conn: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Update columns in *table* matching *where*.

        Enforces ``require_pk_in_where=True`` via
        :meth:`parrot.security.QueryValidator.validate_sql_ast`.

        Args:
            table: Target table.
            data: Columns to SET and their new values.
            where: Columns and values for the WHERE clause (PK must be present).
            returning: Optional RETURNING columns.
            conn: Optional existing transaction connection.

        Returns:
            Updated row dict, or ``{"status": "ok"}``.

        Raises:
            ValueError: Table not in whitelist or WHERE lacks a PK column.
            pydantic.ValidationError: Invalid field in *data*.
            RuntimeError: QueryValidator rejects the generated SQL.
        """
        from parrot.security import QueryValidator

        schema, table_name, meta = self._resolve_table(table)
        Model = self._get_or_build_pydantic_model(meta)
        validated_data = Model(**data).model_dump(exclude_none=True)
        validated_where = Model(**where).model_dump(exclude_none=True)

        set_columns = list(validated_data.keys())
        where_columns = list(validated_where.keys())

        sql, param_order = self._get_or_build_template(
            "update", schema, table_name, meta,
            set_columns=tuple(set_columns),
            where_columns=tuple(where_columns),
            returning=tuple(returning) if returning else None,
        )

        # Enforce PK-in-WHERE safety
        check = QueryValidator.validate_sql_ast(
            sql,
            dialect="postgres",
            read_only=False,
            require_pk_in_where=True,
            primary_keys=meta.primary_keys,
        )
        if not check.get("is_safe"):
            raise RuntimeError(
                f"UPDATE rejected by QueryValidator: {check.get('message')}"
            )

        json_cols = self._json_cols_for(meta)
        combined = {**validated_data, **validated_where}
        args = self._prepare_args(combined, param_order, json_cols)

        return await self._execute_crud(sql, args, returning, conn, single_row=True)

    async def delete_row(
        self,
        table: str,
        where: Dict[str, Any],
        returning: Optional[List[str]] = None,
        conn: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Delete rows from *table* matching *where*.

        Enforces ``require_pk_in_where=True`` via
        :meth:`parrot.security.QueryValidator.validate_sql_ast`.

        Args:
            table: Target table.
            where: Columns and values for the WHERE clause (PK must be present).
            returning: Optional RETURNING columns.
            conn: Optional existing transaction connection.

        Returns:
            Deleted row dict, or ``{"status": "ok"}``.

        Raises:
            ValueError: Table not in whitelist or WHERE lacks a PK column.
            RuntimeError: QueryValidator rejects the generated SQL.
        """
        from parrot.security import QueryValidator

        schema, table_name, meta = self._resolve_table(table)
        Model = self._get_or_build_pydantic_model(meta)
        validated_where = Model(**where).model_dump(exclude_none=True)

        where_columns = list(validated_where.keys())
        sql, param_order = self._get_or_build_template(
            "delete", schema, table_name, meta,
            where_columns=tuple(where_columns),
            returning=tuple(returning) if returning else None,
        )

        check = QueryValidator.validate_sql_ast(
            sql,
            dialect="postgres",
            read_only=False,
            require_pk_in_where=True,
            primary_keys=meta.primary_keys,
        )
        if not check.get("is_safe"):
            raise RuntimeError(
                f"DELETE rejected by QueryValidator: {check.get('message')}"
            )

        json_cols = self._json_cols_for(meta)
        args = self._prepare_args(validated_where, param_order, json_cols)

        return await self._execute_crud(sql, args, returning, conn, single_row=True)

    async def select_rows(
        self,
        table: str,
        where: Optional[Dict[str, Any]] = None,
        columns: Optional[List[str]] = None,
        order_by: Optional[List[str]] = None,
        limit: Optional[int] = None,
        conn: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Select rows from *table*.

        Args:
            table: Target table.
            where: Optional equality filter (``AND``-joined).
            columns: Columns to retrieve.  ``None`` → all.
            order_by: ORDER BY expressions, e.g. ``["created_at DESC"]``.
            limit: Max rows.
            conn: Optional existing connection.

        Returns:
            List of row dicts.

        Raises:
            ValueError: Table not in whitelist.
        """
        schema, table_name, meta = self._resolve_table(table)
        where = where or {}

        where_columns = list(where.keys()) if where else None
        sql, param_order = self._get_or_build_template(
            "select", schema, table_name, meta,
            columns=tuple(columns) if columns else None,
            where_columns=tuple(where_columns) if where_columns else None,
            order_by=tuple(order_by) if order_by else None,
            limit=limit,
        )
        json_cols = self._json_cols_for(meta)
        args = self._prepare_args(where, param_order, json_cols) if where else ()

        result = await self._execute_crud(sql, args, columns or ["*"], conn, single_row=False)
        if isinstance(result, list):
            return result
        return []

    async def _execute_crud(
        self,
        sql: str,
        args: tuple[Any, ...],
        returning: Optional[List[str]],
        conn: Optional[Any],
        single_row: bool,
    ) -> Any:
        """Execute *sql* with *args* using the given or acquired connection.

        Dispatches to ``conn.execute`` (no rows), ``conn.fetchrow`` (single
        row), or ``conn.fetch`` (multiple rows) depending on *returning* and
        *single_row*.
        """
        if conn is not None:
            return await self._run_on_conn(sql, args, returning, conn, single_row)

        async with self._acquire_asyncdb_connection() as acquired_conn:
            return await self._run_on_conn(sql, args, returning, acquired_conn, single_row)

    @staticmethod
    async def _run_on_conn(
        sql: str,
        args: tuple[Any, ...],
        returning: Optional[List[str]],
        conn: Any,
        single_row: bool,
    ) -> Any:
        """Execute on a concrete connection object."""
        if not returning:
            await conn.execute(sql, *args)
            return {"status": "ok"}
        if single_row:
            row = await conn.fetchrow(sql, *args)
            return dict(row) if row else {}
        else:
            rows = await conn.fetch(sql, *args)
            return [dict(r) for r in rows] if rows else []

    # ------------------------------------------------------------------
    # Transaction context manager
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        """Yield an asyncdb connection inside a transaction block.

        Commits on normal exit, rolls back on exception.  Only top-level
        transactions are supported — nested calls raise ``RuntimeError``.

        Yields:
            A connection object that can be passed as ``conn=`` to CRUD
            methods to share a single transaction.

        Raises:
            RuntimeError: When called while already inside a transaction.

        Example::

            async with toolkit.transaction() as tx:
                await toolkit.insert_row("auth.programs", data, conn=tx)
                await toolkit.upsert_row("auth.program_clients", pc, conn=tx)
        """
        if self._in_transaction:
            raise RuntimeError(
                "Nested transactions are not supported. "
                "Complete the current transaction before starting a new one."
            )
        self._in_transaction = True
        try:
            async with self._acquire_asyncdb_connection() as conn:
                async with conn.transaction():
                    try:
                        yield conn
                    except Exception:
                        self._in_transaction = False
                        raise
        finally:
            self._in_transaction = False

    # ------------------------------------------------------------------
    # Metadata reload
    # ------------------------------------------------------------------

    async def reload_metadata(self, schema_name: str, table: str) -> None:
        """Purge and lazily re-warm cached metadata + templates for (schema_name, table).

        Clears:
        * The ``cache_partition`` entry for ``schema_name.table`` (both
          ``schema_cache`` and ``hot_cache`` if accessible).
        * All ``_prepared_cache`` keys containing ``|schema_name|table|``.
        * The global Pydantic model LRU cache (whole cache — documented
          blast radius; see implementation notes).

        The next CRUD call will trigger a lazy re-warm via
        ``_resolve_table → _build_table_metadata``.

        Args:
            schema_name: Schema of the table to invalidate.  Named
                ``schema_name`` (not ``schema``) to avoid the Pydantic v2
                ``BaseModel.schema`` class-method shadowing warning when
                the tool-args model is generated.
            table: Table name to invalidate.
        """
        # Internal alias for readability
        schema = schema_name

        # Clear schema_cache entry
        if self.cache_partition:
            sc = getattr(self.cache_partition, "schema_cache", {})
            schema_meta = sc.get(schema)
            if schema_meta:
                tables_dict = getattr(schema_meta, "tables", {})
                tables_dict.pop(table, None)

            # Clear hot_cache entry
            hot_cache = getattr(self.cache_partition, "hot_cache", None)
            if hot_cache is not None:
                hot_key = f"{schema}.{table}"
                hot_cache.pop(hot_key, None)

        # Clear prepared statement cache entries for this table
        prefix = f"|{schema}|{table}|"
        stale_keys = [k for k in self._prepared_cache if prefix in k]
        for k in stale_keys:
            del self._prepared_cache[k]

        # Clear json_cols cache
        self._json_cols_cache.pop(f"{schema}.{table}", None)

        # Clear global Pydantic model cache
        previous_size = _crud._build_pydantic_model.cache_info().currsize
        _crud._build_pydantic_model.cache_clear()
        self.logger.info(
            "Cleared Pydantic model cache — %d entries evicted for %s.%s",
            previous_size,
            schema,
            table,
        )
