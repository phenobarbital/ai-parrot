"""SQLToolkit — common SQL operations with overridable dialect hooks.

Inherits ``DatabaseToolkit`` and implements schema search, query generation,
execution, explain, and validation for SQL databases.  Dialect differences
(PostgreSQL vs BigQuery vs MySQL) are handled via overridable ``_get_*``
hook methods.

All execution goes through asyncdb — the asyncpg-native path is the only
supported backend. Query builders emit ``$1, $2, …`` positional placeholders.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from ..cache import CachePartition
from ..models import (
    Completeness,
    QueryExecutionResponse,
    TableMetadata,
)
from ..retries import QueryRetryConfig, RetryContext, SQLRetryHandler
from .base import DatabaseToolkit


# Matches leading SQL/PL-pgSQL comments and whitespace so we can identify the
# first significant keyword. Used by ``explain_query`` safety guard to decide
# whether ``EXPLAIN ANALYZE`` is safe (read-only) or must fall back to the
# planner-only variant.
_LEADING_NOISE_RE = re.compile(
    r"^(?:\s+|--[^\n]*\n|/\*.*?\*/)*",
    re.DOTALL,
)

# A CTE may still be a write — ``WITH ... DELETE`` / ``UPDATE`` / ``INSERT``
# / ``MERGE`` inside a CTE mutates data and must NOT be run with ANALYZE.
_CTE_DML_RE = re.compile(
    r"\b(insert|update|delete|merge|truncate|drop|alter|create|grant|revoke)\b",
    re.IGNORECASE,
)

#: Map ``DatabaseToolkit.database_type`` values to sqlglot dialect names.
_SQLGLOT_DIALECT_MAP: Dict[str, str] = {
    "postgresql": "postgres",
    "postgres": "postgres",
    "bigquery": "bigquery",
    "mysql": "mysql",
    "mariadb": "mysql",
    "sqlite": "sqlite",
    "mssql": "tsql",
    "sqlserver": "tsql",
    "oracle": "oracle",
    "clickhouse": "clickhouse",
    "duckdb": "duckdb",
    "redshift": "redshift",
    "snowflake": "snowflake",
}


class SQLToolkit(DatabaseToolkit):
    """Common SQL operations with overridable dialect hooks.

    Subclass and override the ``_get_*`` methods to customize behaviour for
    specific SQL dialects (PostgreSQL, BigQuery, etc.).
    """

    # Extend parent exclude_tools — private _get_* hooks start with '_' and
    # are auto-excluded by AbstractToolkit, but we add extras here.
    exclude_tools: tuple[str, ...] = (
        "start",
        "stop",
        "cleanup",
        "get_table_metadata",
        "health_check",
    )

    # Subclasses that migrate to pg_catalog override this to "pg_catalog".
    _metadata_source: str = "information_schema"

    def __init__(
        self,
        dsn: str,
        allowed_schemas: Optional[List[str]] = None,
        primary_schema: Optional[str] = None,
        tables: Optional[List[str]] = None,
        read_only: bool = True,
        cache_partition: Optional[CachePartition] = None,
        retry_config: Optional[QueryRetryConfig] = None,
        database_type: str = "postgresql",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            dsn=dsn,
            allowed_schemas=allowed_schemas,
            primary_schema=primary_schema,
            tables=tables,
            read_only=read_only,
            cache_partition=cache_partition,
            retry_config=retry_config,
            database_type=database_type,
            **kwargs,
        )
        # Coalescing map for concurrent introspection calls (Module 3, FEAT-178)
        self._inflight: Dict[Tuple[str, str], asyncio.Future] = {}
        self._inflight_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # LLM-callable tool methods
    # ------------------------------------------------------------------

    async def search_schema(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[TableMetadata]:
        """Search schema identifiers (table/column/comment names) matching *search_term*.

        Searches identifiers (table/column/comment names), not data values.
        Merges cache and live DB results, deduplicates by (schema, tablename)
        preferring the higher-completeness entry on collision, and returns
        results sorted by relevance score descending.

        Args:
            search_term: Keyword or pattern to match.
            schema_name: Restrict to a specific schema.
            limit: Maximum results.

        Returns:
            Matching ``TableMetadata`` list, sorted by relevance descending.
        """
        # Auto-detect "schema table" pattern when schema_name is not explicit.
        # If the first word of search_term matches a known allowed schema,
        # scope the search to that schema and use the remainder as the term.
        if schema_name is None and " " in search_term.strip():
            parts = search_term.strip().split(None, 1)
            if parts[0].lower() in {s.lower() for s in self.allowed_schemas}:
                schema_name = parts[0]
                search_term = parts[1]
                self.logger.debug(
                    "search_schema: auto-split '%s %s' → schema_name=%r search_term=%r",
                    schema_name, search_term, schema_name, search_term,
                )

        target_schemas = [schema_name] if schema_name else self.allowed_schemas

        cache_hits: List[TableMetadata] = []
        if self.cache_partition is not None:
            cache_hits = await self.cache_partition.search(
                target_schemas, search_term,
                completeness_min=Completeness.NAME_ONLY, limit=limit,
            )

        db_hits = await self._search_in_database(search_term, schema_name, limit)

        # Merge, preferring higher completeness on (schema, tablename) collision
        merged: Dict[Tuple[str, str], TableMetadata] = {}
        for m in (*cache_hits, *db_hits):
            key = (m.schema, m.tablename)
            if key not in merged or m.completeness > merged[key].completeness:
                merged[key] = m

        if not merged:
            return []

        if self.cache_partition is not None:
            keywords = self.cache_partition._extract_search_keywords(search_term)
            scored = [
                (
                    self.cache_partition._calculate_relevance_score(m.tablename, m, keywords),
                    m,
                )
                for m in merged.values()
            ]
        else:
            scored = [(0.0, m) for m in merged.values()]

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:limit]]

    async def describe_table(
        self,
        schema: str,
        table: str,
    ) -> Optional[TableMetadata]:
        """Return full-completeness metadata for *schema.table*.

        Checks the cache first. If the cached entry does not satisfy
        ``Completeness.FULL``, introspects the table via the DB and stores
        the result in the cache.

        Args:
            schema: Schema name.
            table: Table name.

        Returns:
            ``TableMetadata`` with ``completeness == FULL``, or ``None``
            if the table does not exist.
        """
        if self.cache_partition is not None:
            cached = await self.cache_partition.get(
                schema, table, required=Completeness.FULL,
            )
            if cached is not None:
                return cached

        meta = await self._introspect_table_full(schema, table)
        if meta is not None and self.cache_partition is not None:
            await self.cache_partition.store_table_metadata(meta)
        return meta

    async def generate_query(
        self,
        natural_language: str,
        target_tables: Optional[List[str]] = None,
        query_type: str = "SELECT",
    ) -> str:
        """Prepare a SQL skeleton and schema context for SQL generation.

        Ensures every referenced table has FULL completeness metadata before
        building the context so the LLM never sees ``columns: []`` stubs.
        Accepts entries as ``"schema.table"`` or bare ``"table"`` names;
        bare names are resolved across ``allowed_schemas``.

        Args:
            natural_language: User's question in plain English.
            target_tables: Optional list of ``"schema.table"`` or bare
                ``"table"`` names.  When empty, ``search_schema`` is used
                to discover candidates (top 3).
            query_type: Hint for query type (SELECT, INSERT, etc.).

        Returns:
            Skeleton SQL string plus per-table YAML metadata context.
        """
        resolved: List[TableMetadata] = []

        if target_tables:
            for entry in target_tables:
                if "." in entry:
                    schema, tbl = entry.split(".", 1)
                    meta = await self.describe_table(schema, tbl)
                    if meta is not None:
                        resolved.append(meta)
                else:
                    for schema in self.allowed_schemas:
                        meta = await self.describe_table(schema, entry)
                        if meta is not None:
                            resolved.append(meta)
                            break
        else:
            candidates = await self.search_schema(natural_language, limit=5)
            for meta in candidates[:3]:
                full = await self.describe_table(meta.schema, meta.tablename)
                if full is not None:
                    resolved.append(full)

        if not resolved:
            return (
                f"-- Auto-generated {query_type} skeleton (no tables resolved)\n"
                f"-- Query: {natural_language}\n"
                "-- TODO: specify target tables\n"
            )

        skeleton_parts = []
        for meta in resolved:
            col_list = (
                ", ".join(col["name"] for col in meta.columns)
                if meta.columns
                else "*"
            )
            skeleton = (
                f"-- Auto-generated SELECT skeleton (LLM should refine WHERE/JOIN):\n"
                f"SELECT {col_list}\n"
                f"FROM {meta.schema}.{meta.tablename}\n"
                f'-- TODO: WHERE clause for "{natural_language}"\n'
            )
            skeleton_parts.append(f"{skeleton}\n{meta.to_yaml_context()}")

        return "\n---\n".join(skeleton_parts)

    async def execute_query(
        self,
        query: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> Union[QueryExecutionResponse, RetryContext]:
        """Execute a SQL query and return results or a retry context.

        Applies the configured safety policy first.  When ``retry_config`` is
        set and the query fails with a retryable error, returns a
        ``RetryContext`` instead of ``QueryExecutionResponse`` so that
        ``DatabaseAgent.ask()`` can re-ask the LLM with error context.

        Non-retryable exceptions are re-raised when ``retry_config`` is set,
        and wrapped in ``QueryExecutionResponse(success=False)`` otherwise
        (legacy behaviour for callers that don't check the return type).

        Args:
            query: SQL query string.
            limit: Maximum rows to return.
            timeout: Query timeout in seconds.

        Returns:
            ``QueryExecutionResponse`` on success or when retrying is not
            configured; ``RetryContext`` when a retryable error occurs and
            ``retry_config`` is set.

        Raises:
            Exception: For non-retryable errors when ``retry_config`` is set.
        """
        safety_error = self._check_query_safety(query)
        if safety_error is not None:
            self.logger.warning("Query rejected by safety policy: %s", safety_error)
            return QueryExecutionResponse(
                success=False,
                row_count=0,
                execution_time_ms=0.0,
                schema_used=self.primary_schema,
                error_message=f"Query blocked by safety policy: {safety_error}",
            )

        retry_cfg: Optional[QueryRetryConfig] = getattr(self, "retry_config", None)
        start = time.monotonic()
        try:
            data = await self._run_query(query, limit=limit, timeout=timeout)
            elapsed = (time.monotonic() - start) * 1000
            return QueryExecutionResponse(
                success=True,
                row_count=len(data),
                columns=list(data[0].keys()) if data else [],
                data=data,
                execution_time_ms=elapsed,
                schema_used=self.primary_schema,
            )
        except Exception as err:
            elapsed = (time.monotonic() - start) * 1000
            if retry_cfg is None:
                # Legacy path: no retry config → swallow and return failure response.
                self.logger.error("Query execution failed: %s", err)
                return QueryExecutionResponse(
                    success=False,
                    row_count=0,
                    execution_time_ms=elapsed,
                    schema_used=self.primary_schema,
                    error_message=str(err),
                )
            handler = SQLRetryHandler(toolkit=self, config=retry_cfg)
            if not handler._is_retryable_error(err):
                raise
            # Retryable error — collect sample data and return RetryContext.
            table, column = handler._extract_table_column_from_error(query, err)
            sample_data = ""
            if table and column:
                try:
                    sample_data = await handler._get_sample_data_for_error(
                        self.primary_schema, table, column
                    )
                except Exception:
                    pass
            correction = await handler.retry_query(query, err, attempt=1)
            return RetryContext(
                query=query,
                error=str(err),
                attempt=1,
                sample_data=sample_data,
                suggested_correction=correction,
            )

    async def explain_query(self, query: str) -> str:
        """Run an EXPLAIN on the given query and return the plan.

        Safety: ``EXPLAIN ANALYZE`` actually **executes** the statement —
        for ``DELETE``/``UPDATE``/``INSERT``/``MERGE`` this would mutate
        data, which the read-only DBA-helper use case must never do. When
        the query is not provably read-only we strip ``ANALYZE`` (and any
        execution-time options) and run the planner-only variant.

        Args:
            query: SQL query to explain.

        Returns:
            Execution plan text.
        """
        if self._is_read_only_query(query):
            prefix = self._get_explain_prefix()
        else:
            prefix = self._get_explain_prefix_planner_only()
            self.logger.info(
                "explain_query: stripping ANALYZE — query is not read-only"
            )
        explain_sql = f"{prefix} {query}"
        try:
            data, error = await self._execute_asyncdb(explain_sql, limit=0, timeout=60)
            if error:
                return f"EXPLAIN failed: {error}"
            if data:
                return "\n".join(str(row) for row in data)
            return "No plan returned."
        except Exception as exc:
            return f"EXPLAIN failed: {exc}"

    def _is_read_only_query(self, query: str) -> bool:
        """Return ``True`` when *query* has no side effects on the database.

        Accepts queries whose first significant keyword is ``SELECT``,
        ``WITH``, ``VALUES``, ``SHOW``, or ``TABLE``. ``WITH`` is only
        considered safe if its body does not reference DML/DDL keywords
        (CTE may still wrap an ``UPDATE``/``DELETE``).

        This is a conservative check — false negatives (a SELECT
        misclassified as unsafe) only mean the plan is generated without
        ANALYZE, which is correct and just less detailed. False positives
        (DML misclassified as safe) would defeat the safety guard, so the
        check errs on the side of stripping ANALYZE.
        """
        if not query:
            return False
        stripped = _LEADING_NOISE_RE.sub("", query).lstrip().lower()
        if not stripped:
            return False
        first_word, _, _ = stripped.partition(" ")
        first_word = first_word.strip("(")  # tolerate "(SELECT ..."
        if first_word in {"select", "values", "show", "table"}:
            return True
        if first_word == "with":
            # CTE: scan the body for DML/DDL.
            return _CTE_DML_RE.search(stripped) is None
        return False

    def _get_explain_prefix_planner_only(self) -> str:
        """Return an EXPLAIN prefix that does NOT execute the statement.

        Subclasses override this when their default prefix runs the query
        (e.g. PostgreSQL's ``EXPLAIN (ANALYZE, ...)``). The base
        implementation returns plain ``EXPLAIN`` which is planner-only on
        every major dialect.
        """
        return "EXPLAIN"

    @staticmethod
    def _stem_variants(search_term: str) -> List[str]:
        """Generate fallback search terms by truncating the longest token.

        Examples:
            "category"          -> ["categor", "catego"]      (drop 1, 2)
            "user_orders"       -> ["user_order", "user_ord"]
            "ab"                -> []                          (too short)
            "users orders"      -> ["users", "user"]           (use longest)

        We only stem the **longest token** (≥ 6 chars). Anything shorter
        is unlikely to have a meaningful suffix swap and stemming risks
        false positives ("user" → "use", "us" — too generic).

        When the caller passes a full natural-language sentence (e.g. the
        prefetch in ``DatabaseAgent.ask`` forwards the entire user prompt
        as the ``search_term``), we short-circuit and return ``[]``: the
        first ILIKE on a sentence-length pattern will never match anyway,
        and 2× retries on garbage stems just burn DB roundtrips. The
        sentence heuristic: >5 whitespace-separated words OR length > 60.
        """
        if not search_term:
            return []
        stripped_term = search_term.strip()
        if not stripped_term:
            return []
        # Skip sentences entirely — they are not useful for ILIKE search and
        # were never going to hit on retries either.
        if len(stripped_term) > 60 or len(stripped_term.split()) > 5:
            return []
        tokens = re.split(r"(\W+)", stripped_term)
        if not tokens:
            return []
        # Find the longest non-delimiter token (delimiters land on odd indices)
        idx_longest = max(
            (i for i in range(0, len(tokens), 2) if i < len(tokens)),
            key=lambda i: len(tokens[i]) if tokens[i].isalnum() else 0,
            default=-1,
        )
        if idx_longest < 0:
            return []
        longest = tokens[idx_longest]
        if len(longest) < 6:
            return []
        variants: List[str] = []
        # Strategy A: stem-trim the longest token in place (preserves
        # delimiters / surrounding tokens). Handles "category" → "categor".
        for trim in (1, 2):
            if len(longest) - trim < 4:
                break
            stem = longest[: -trim]
            new_tokens = list(tokens)
            new_tokens[idx_longest] = stem
            variants.append("".join(new_tokens))
        # Strategy B: when the search has multiple alphanumeric tokens, the
        # discriminating word is usually the longest one — fall back to the
        # bare longest token (and its stem) so e.g. ``"orders table"`` also
        # tries ``"orders"`` and ``"order"``.
        word_count = sum(1 for i in range(0, len(tokens), 2) if i < len(tokens) and tokens[i].isalnum())
        if word_count > 1:
            variants.append(longest)
            if len(longest) >= 5:
                variants.append(longest[:-1])
        # Dedupe preserving order
        return list(dict.fromkeys(variants))

    async def validate_query(self, sql: str) -> Dict[str, Any]:
        """Validate SQL syntax and referenced objects.

        Args:
            sql: SQL query to validate.

        Returns:
            Dict with ``valid``, ``errors``, and ``referenced_tables`` keys.
        """
        import re

        errors: list[str] = []
        referenced: list[str] = []

        # Extract table references from FROM / JOIN clauses
        from_pattern = r'(?:FROM|JOIN)\s+(?:"?(\w+)"?\.)?"?(\w+)"?'
        matches = re.findall(from_pattern, sql, re.IGNORECASE)
        for schema_part, table_part in matches:
            schema = schema_part or self.primary_schema
            referenced.append(f"{schema}.{table_part}")

            # Verify table exists in cache
            if self.cache_partition:
                meta = await self.cache_partition.get_table_metadata(schema, table_part)
                if meta is None:
                    errors.append(f"Table '{schema}.{table_part}' not found in cache.")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "referenced_tables": referenced,
            "sql": sql,
        }

    # ------------------------------------------------------------------
    # Safety policy (called by execute_query before running)
    # ------------------------------------------------------------------

    def _check_query_safety(self, sql: str) -> Optional[str]:
        """Return an error message if *sql* must be rejected, ``None`` otherwise.

        Uses :meth:`parrot.security.QueryValidator.validate_sql_ast` (sqlglot
        AST parse) when sqlglot is available — this reliably catches DDL,
        multi-statement, and missing-WHERE cases even when keywords appear
        inside string literals. Falls back to the regex validator when
        sqlglot cannot be imported.

        Policy:
          * ``read_only=True`` (default) — only SELECT/WITH/EXPLAIN/SHOW/
            DESCRIBE permitted.
          * ``read_only=False`` — DML permitted; DDL and multi-statement
            always blocked; UPDATE/DELETE must include a WHERE clause.
        """
        from ....security import QueryValidator

        dialect = _SQLGLOT_DIALECT_MAP.get(self.database_type)
        result = QueryValidator.validate_sql_ast(
            sql, dialect=dialect, read_only=self.read_only
        )
        if not result.get("is_safe", False):
            return result.get("message", "Query rejected by validator")
        return None

    # ------------------------------------------------------------------
    # Cache warm-up (called by DatabaseToolkit.start when tables is set)
    # ------------------------------------------------------------------

    async def _warm_table_cache(self) -> None:
        """Pre-populate ``cache_partition`` for each entry in ``self.tables``.

        Entries use ``"schema.table"`` format; bare ``"table"`` falls back to
        ``self.primary_schema``. Missing or introspection-failed tables log a
        warning and are skipped rather than raising.
        """
        if not self.tables:
            return
        if self.cache_partition is None:
            self.logger.debug(
                "No cache_partition on %s; skipping warm-up of %d tables",
                self.__class__.__name__,
                len(self.tables),
            )
            return

        warmed = 0
        for entry in self.tables:
            parsed = self._parse_table_entry(entry)
            if parsed is None:
                self.logger.warning(
                    "Skipping malformed 'tables' entry: %r", entry
                )
                continue
            schema, table = parsed
            try:
                metadata = await self._build_table_metadata(
                    schema, table, "BASE TABLE", None
                )
            except Exception as exc:
                self.logger.warning(
                    "Warm-up failed for %s.%s: %s", schema, table, exc
                )
                continue
            if metadata is None or not metadata.columns:
                self.logger.warning(
                    "Warm-up skipped %s.%s (table not found or no columns)",
                    schema,
                    table,
                )
                continue
            await self.cache_partition.store_table_metadata(metadata)
            warmed += 1

        self.logger.info(
            "%s warmed metadata cache for %d/%d tables",
            self.__class__.__name__,
            warmed,
            len(self.tables),
        )

    # ------------------------------------------------------------------
    # Overridable dialect hooks (private — not exposed as tools)
    # ------------------------------------------------------------------

    def _get_explain_prefix(self) -> str:
        """Return the EXPLAIN statement prefix for this SQL dialect."""
        return "EXPLAIN ANALYZE"

    def _get_information_schema_query(
        self,
        search_term: str,
        schemas: List[str],
        limit: int = 20,
    ) -> tuple[str, tuple]:
        """Return ``(sql, params)`` for table discovery via information_schema.

        Emits ``$1, $2, …`` asyncpg positional placeholders.
        Override in subclasses for dialect-specific introspection.

        Args:
            search_term: Term to match against table names.
            schemas: List of schema names to search.
            limit: Maximum rows to return (bound as ``$3``).

        Returns:
            ``(sql, params_tuple)`` ready for :meth:`_execute_asyncdb`.
        """
        sql = """
            SELECT DISTINCT
                table_schema,
                table_name,
                table_type
            FROM information_schema.tables
            WHERE table_schema = ANY($1)
            AND (
                table_name ILIKE $2
                OR (table_schema || '.' || table_name) ILIKE $2
            )
            AND table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY table_name
            LIMIT $3
        """
        return sql, (schemas, f"%{search_term}%", limit)

    def _get_columns_query(self, schema: str, table: str) -> tuple[str, tuple]:
        """Return ``(sql, params)`` for column metadata.

        Args:
            schema: Schema name.
            table: Table name.

        Returns:
            ``(sql, params_tuple)`` with ``$1=schema, $2=table``.
        """
        sql = """
            SELECT column_name, data_type, is_nullable, column_default,
                   ordinal_position
            FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position
        """
        return sql, (schema, table)

    def _get_primary_keys_query(self, schema: str, table: str) -> tuple[str, tuple]:
        """Return ``(sql, params)`` for primary key columns.

        Args:
            schema: Schema name.
            table: Table name.

        Returns:
            ``(sql, params_tuple)`` with ``$1=schema, $2=table``.
        """
        sql = """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
            AND tc.table_schema = $1
            AND tc.table_name = $2
            ORDER BY kcu.ordinal_position
        """
        return sql, (schema, table)

    def _get_unique_constraints_query(
        self, schema: str, table: str
    ) -> tuple[str, tuple]:
        """Return ``(sql, params)`` for UNIQUE constraint columns of (schema, table).

        Queries ``information_schema.table_constraints`` joined with
        ``information_schema.key_column_usage`` to list each UNIQUE
        constraint and its member columns in ordinal order.

        Subclasses (e.g. ``PostgresToolkit``) may override this to also
        capture UNIQUE indexes not backed by named constraints.

        Args:
            schema: Schema name.
            table: Table name.

        Returns:
            Tuple of ``(sql, params)`` ready for :meth:`_execute_asyncdb`.
        """
        sql = """
            SELECT
                tc.constraint_name,
                kcu.column_name,
                kcu.ordinal_position
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON kcu.constraint_name = tc.constraint_name
               AND kcu.table_schema   = tc.table_schema
               AND kcu.table_name     = tc.table_name
            WHERE tc.table_schema   = $1
              AND tc.table_name     = $2
              AND tc.constraint_type = 'UNIQUE'
            ORDER BY tc.constraint_name, kcu.ordinal_position
        """
        return sql, (schema, table)

    def _get_sample_data_query(
        self, schema: str, table: str, limit: int = 3
    ) -> str:
        """Return SQL for fetching sample rows."""
        safe_schema = self._validate_identifier(schema)
        safe_table = self._validate_identifier(table)
        return f'SELECT * FROM "{safe_schema}"."{safe_table}" LIMIT {int(limit)}'

    # ------------------------------------------------------------------
    # Internal execution helpers
    # ------------------------------------------------------------------

    async def _run_query(
        self,
        query: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> List[Dict[str, Any]]:
        """Execute SQL and return raw row data, raising on any error.

        Args:
            query: SQL to execute.
            limit: Maximum rows to return.
            timeout: Query timeout in seconds.

        Returns:
            List of row dicts (may be empty).

        Raises:
            Exception: With the database error message if execution fails.
        """
        data, error = await self._execute_asyncdb(query, limit=limit, timeout=timeout)
        if error:
            raise Exception(error)
        return data or []

    async def _execute_asyncdb(
        self,
        sql: str,
        params: tuple = (),
        limit: int = 1000,
        timeout: int = 30,
    ) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """Execute SQL via asyncdb and return ``(data, error)``.

        Uses the raw ``asyncpg.Connection`` obtained from
        :meth:`_acquire_asyncdb_connection` (boundary-unwrapped).

        Args:
            sql: SQL query with ``$N`` positional placeholders.
            params: Positional parameters tuple (default: empty).
            limit: Maximum rows to return (0 = no limit).
            timeout: Query timeout in seconds (unused by asyncpg fetch,
                kept for interface compatibility).

        Returns:
            ``(data, None)`` on success or ``(None, error_str)`` on failure.
        """
        if self._connection is None:
            return None, "Not connected (call start() first)"
        try:
            async with self._acquire_asyncdb_connection() as conn:
                # conn.fetch(sql, *()) is identical to conn.fetch(sql) in asyncpg.
                rows = await conn.fetch(sql, *params)
                if rows is None:
                    return [], None
                data = [dict(row) for row in rows]
                if limit and len(data) > limit:
                    data = data[:limit]
                return data, None
        except Exception as exc:
            return None, str(exc)

    async def _search_in_database(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[TableMetadata]:
        """Query information_schema for matching tables and build metadata.

        Metadata for the matching tables is fetched in parallel — every
        ``_build_table_metadata`` call is independent (one connection
        acquire per call from the pool) and previously dominated wall time
        because we awaited each table sequentially. Order is preserved by
        zipping the gathered results back against the ``information_schema``
        row order.

        Stem-fallback: the LLM frequently searches for the singular root of
        a concept (e.g. ``"category"``) but tables are named with the
        plural (``"products_categories"``). ``ILIKE %category%`` does not
        match ``products_categories`` because the suffix differs (``y`` vs
        ``ies``). When the exact term returns nothing we retry with a
        progressively shorter prefix of the longest token so plural/
        singular variants do match. We do NOT pre-merge these into a single
        OR'd query because that would slow the common case (where the
        first pattern hits) by forcing an additional planner pass on every
        call.
        """
        target_schemas = [schema_name] if schema_name else self.allowed_schemas

        async def _run(pattern: str) -> tuple[Optional[list], Optional[str]]:
            info_sql, params = self._get_information_schema_query(pattern, target_schemas, limit)
            try:
                return await self._execute_asyncdb(info_sql, params=params, limit=limit, timeout=30)
            except Exception as exc:
                self.logger.warning("Schema search failed: %s", exc)
                return None, str(exc)

        data, error = await _run(search_term)

        if (not data) and not error:
            for fallback in self._stem_variants(search_term):
                self.logger.debug(
                    "search_schema: retrying with stem %r (no hits for %r)",
                    fallback, search_term,
                )
                data, error = await _run(fallback)
                if data:
                    break

        if error or not data:
            return []

        rows = [
            (
                row.get("table_schema", self.primary_schema),
                row.get("table_name", ""),
                row.get("table_type", "BASE TABLE"),
                row.get("comment"),
            )
            for row in data
            if row.get("table_name")
        ]
        if not rows:
            return []

        # Bound the per-table fan-out. Each ``_build_table_metadata`` call
        # fires three concurrent information_schema queries internally, all
        # routed through the same ``asyncdb`` driver instance. Without a
        # semaphore, a 10-table result set produces ~30 simultaneous
        # ``connection()`` calls and trips
        #     asyncpg.exceptions._base.InternalClientError:
        #         got result for unknown protocol state 3
        # because the underlying asyncpg protocol object is not safe under
        # that level of concurrent re-entry. Four-at-a-time keeps total
        # in-flight queries at ~12 which the pool comfortably handles.
        sem = asyncio.Semaphore(4)

        async def _with_sem(s: str, t: str, tt: str, c: Optional[str]):
            async with sem:
                return await self._build_table_metadata(s, t, tt, c)

        metadata_list = await asyncio.gather(
            *(_with_sem(s, t, tt, c) for s, t, tt, c in rows),
            return_exceptions=False,
        )

        results: List[TableMetadata] = []
        for metadata in metadata_list:
            if metadata is None:
                continue
            if self.cache_partition:
                await self.cache_partition.store_table_metadata(metadata)
            results.append(metadata)

        return results[:limit]

    async def _introspect_table_full(
        self,
        schema: str,
        table: str,
    ) -> Optional[TableMetadata]:
        """Fully introspect *schema.table* with concurrency coalescing.

        Concurrent calls for the same key share a single DB round-trip —
        the first caller performs the query and the rest await its Future.
        """
        key = (schema, table)

        async with self._inflight_lock:
            existing = self._inflight.get(key)
            if existing is not None:
                future = existing
                owner = False
            else:
                future = asyncio.get_running_loop().create_future()
                # Prevent "Future exception was never retrieved" when no waiters exist
                future.add_done_callback(
                    lambda f: f.exception() if not f.cancelled() and f.exception() is not None else None
                )
                self._inflight[key] = future
                owner = True

        if not owner:
            return await future

        try:
            meta = await self._build_table_metadata(
                schema, table, table_type="BASE TABLE",
            )
            if meta is not None:
                meta.completeness = Completeness.FULL
                meta.source = self._metadata_source
            future.set_result(meta)
            return meta
        except Exception as exc:  # noqa: BLE001
            future.set_exception(exc)
            raise
        finally:
            async with self._inflight_lock:
                self._inflight.pop(key, None)

    async def _build_table_metadata(
        self,
        schema: str,
        table: str,
        table_type: str,
        comment: Optional[str] = None,
    ) -> Optional[TableMetadata]:
        """Build a ``TableMetadata`` object by querying column and key info.

        The three information_schema queries (columns, primary keys, unique
        constraints) are issued concurrently — they are independent and the
        bottleneck of ``search_schema`` was previously the serial await on
        each. The unique-constraints query is treated as best-effort: any
        exception is swallowed (logged at DEBUG) and the table is still
        returned with the column / primary-key info we managed to fetch.
        """
        col_sql, col_params = self._get_columns_query(schema, table)
        pk_sql, pk_params = self._get_primary_keys_query(schema, table)
        uq_sql, uq_params = self._get_unique_constraints_query(schema, table)

        try:
            col_result, pk_result, uq_result = await asyncio.gather(
                self._execute_asyncdb(col_sql, params=col_params, limit=0, timeout=15),
                self._execute_asyncdb(pk_sql, params=pk_params, limit=0, timeout=15),
                self._execute_asyncdb(uq_sql, params=uq_params, limit=0, timeout=15),
                return_exceptions=True,
            )
        except Exception as exc:
            self.logger.warning("Failed to build metadata for %s.%s: %s", schema, table, exc)
            return None

        try:
            if isinstance(col_result, Exception):
                self.logger.warning(
                    "Column introspection failed for %s.%s: %s", schema, table, col_result
                )
                col_data = None
            else:
                col_data, _ = col_result
            columns = []
            if col_data:
                for col in col_data:
                    columns.append({
                        "name": col.get("column_name", ""),
                        "type": col.get("data_type", "unknown"),
                        "nullable": col.get("is_nullable", "YES") == "YES",
                        "default": col.get("column_default"),
                    })

            pk_data, _ = pk_result if not isinstance(pk_result, Exception) else (None, str(pk_result))
            primary_keys = [
                row.get("column_name", "") for row in (pk_data or [])
            ]

            unique_constraints: List[List[str]] = []
            if isinstance(uq_result, Exception):
                self.logger.debug(
                    "Failed to fetch UNIQUE constraints for %s.%s: %s",
                    schema, table, uq_result,
                )
            else:
                uq_data, _uq_error = uq_result
                if uq_data:
                    grouped: Dict[str, List[str]] = {}
                    for row in uq_data:
                        constraint_name = row.get("constraint_name", "")
                        column_name = row.get("column_name", "")
                        if constraint_name and column_name:
                            grouped.setdefault(constraint_name, []).append(column_name)
                    unique_constraints = sorted(
                        grouped.values(),
                        key=lambda cols: (cols[0] if cols else ""),
                    )
                else:
                    self.logger.debug(
                        "No UNIQUE constraints found for %s.%s", schema, table
                    )

            return TableMetadata(
                schema=schema,
                tablename=table,
                table_type=table_type,
                full_name=f'"{schema}"."{table}"',
                columns=columns,
                primary_keys=primary_keys,
                foreign_keys=[],
                indexes=[],
                comment=comment,
                unique_constraints=unique_constraints,
                source=self._metadata_source,
            )
        except Exception as exc:
            self.logger.warning("Failed to build metadata for %s.%s: %s", schema, table, exc)
            return None
