"""DatabaseToolkit — abstract base for all database toolkits.

Inherits from ``AbstractToolkit`` (auto-generates tools from public async
methods) and adds the database-specific lifecycle: connect, search schema,
execute queries, cache integration.
"""
from __future__ import annotations
import re
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, TYPE_CHECKING
from pydantic import BaseModel, Field
from ....tools.toolkit import AbstractToolkit
from ..cache import CachePartition
from ..models import (
    QueryExecutionResponse,
    SchemaMetadata,
    TableMetadata,
)
from ..retries import QueryRetryConfig


#: Regex for safe SQL identifiers (letters, digits, underscores).
_SAFE_IDENTIFIER = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

if TYPE_CHECKING:
    pass  # reserved for future type-only imports


# ---------------------------------------------------------------------------
# Configuration model
# ---------------------------------------------------------------------------

class DatabaseToolkitConfig(BaseModel):
    """Configuration passed to toolkit constructors."""

    dsn: Optional[str] = Field(default=None, description="Database connection string")
    allowed_schemas: List[str] = Field(default_factory=lambda: ["public"])
    primary_schema: Optional[str] = Field(default=None)
    tables: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional list of tables to pre-warm the metadata cache during "
            "start(). Accepts 'schema.table' or 'table' (defaults to "
            "primary_schema). Missing/invalid entries are warned and skipped."
        ),
    )
    read_only: bool = Field(
        default=True,
        description=(
            "When True, execute_query() rejects any non-SELECT statement. "
            "When False, DML (INSERT/UPDATE/DELETE) is permitted but DDL "
            "(CREATE/ALTER/DROP/TRUNCATE/GRANT/REVOKE/RENAME) and multi-"
            "statements are always blocked, and UPDATE/DELETE require a "
            "WHERE clause."
        ),
    )
    database_type: str = Field(default="postgresql")
    use_pool: bool = Field(
        default=False,
        description=(
            "When True, connect via ``asyncdb.AsyncPool`` (pool-based) "
            "instead of ``asyncdb.AsyncDB`` (single connection). "
            "Connections are acquired/released per query. Only supported by "
            "drivers that ship a ``<driver>Pool`` class (e.g. ``pg``)."
        ),
    )
    pool_params: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Extra kwargs forwarded to the AsyncPool constructor when "
            "``use_pool=True`` (e.g. ``{'min_size': 5, 'max_clients': 50}``)."
        ),
    )


# ---------------------------------------------------------------------------
# DatabaseToolkit base
# ---------------------------------------------------------------------------

class DatabaseToolkit(AbstractToolkit, ABC):
    """Abstract base class for all database toolkits.

    Subclasses implement the two abstract methods (``search_schema`` and
    ``execute_query``).  All public ``async`` methods are automatically
    converted to LLM-callable tools by ``AbstractToolkit._generate_tools()``.

    Internal lifecycle methods (``start``, ``stop``, ``cleanup``,
    ``get_table_metadata``, ``health_check``) are hidden from the LLM via
    ``exclude_tools``.
    """

    #: Default namespace for all database toolkits. Concrete subclasses that
    #: need to coexist in the same agent (e.g. SQL + Influx) SHOULD override
    #: this with a backend-specific value such as ``"pg"`` or ``"influx"``.
    tool_prefix: str = "db"

    #: Methods hidden from LLM tool generation.
    exclude_tools: tuple[str, ...] = (
        "start",
        "stop",
        "cleanup",
        "get_table_metadata",
        "health_check",
    )

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
        use_pool: bool = False,
        pool_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        # Hard-fail if caller passes the removed `backend=` kwarg.
        # (FEAT-118: SQLAlchemy backend was deleted; zero production callers.)
        if "backend" in kwargs:
            raise TypeError(
                f"{type(self).__name__}.__init__() got an unexpected keyword "
                "argument 'backend'. The 'backend' parameter was removed in "
                "FEAT-118. All connections now use asyncdb exclusively."
            )
        super().__init__(**kwargs)

        # Connection config (lazy — no I/O in __init__)
        self.dsn = dsn
        self.allowed_schemas = allowed_schemas or ["public"]
        self.primary_schema = primary_schema or (
            self.allowed_schemas[0] if self.allowed_schemas else "public"
        )
        self.tables = tables
        self.read_only = read_only
        self.database_type = database_type
        self.use_pool = use_pool
        self.pool_params = pool_params or {}

        # Cache & retry
        self.cache_partition = cache_partition
        self.retry_config = retry_config or QueryRetryConfig()

        # Connection state (populated by start())
        self._connection: Any = None
        self._connected: bool = False

    # ------------------------------------------------------------------
    # Identifier safety
    # ------------------------------------------------------------------

    def _parse_table_entry(self, entry: str) -> Optional[tuple[str, str]]:
        """Parse a ``tables`` list entry into ``(schema, table)``.

        Accepts ``"schema.table"`` (explicit) or ``"table"`` (defaults to
        ``self.primary_schema``). Returns ``None`` for malformed entries.

        Args:
            entry: Raw string from the ``tables`` configuration list.

        Returns:
            Tuple of ``(schema, table)`` or ``None`` if the entry cannot
            be parsed.
        """
        if not isinstance(entry, str) or not entry.strip():
            return None
        cleaned = entry.strip().strip('"')
        if "." in cleaned:
            schema, table = cleaned.split(".", 1)
            schema = schema.strip().strip('"')
            table = table.strip().strip('"')
            if not schema or not table:
                return None
            return schema, table
        return self.primary_schema, cleaned

    async def _warm_table_cache(self) -> None:
        """Pre-populate ``cache_partition`` for every entry in ``self.tables``.

        Base implementation is a no-op — subclasses with schema introspection
        (e.g. ``SQLToolkit``) override this to query metadata once at startup.
        """
        self.logger.debug(
            "%s does not implement table cache warm-up; skipping %d entries",
            self.__class__.__name__,
            len(self.tables or []),
        )

    @staticmethod
    def _validate_identifier(name: str) -> str:
        """Validate that *name* is a safe SQL/database identifier.

        Args:
            name: Identifier to validate.

        Returns:
            The validated identifier.

        Raises:
            ValueError: If the identifier contains unsafe characters.
        """
        if not _SAFE_IDENTIFIER.match(name):
            raise ValueError(f"Invalid SQL identifier: {name!r}")
        return name

    # ------------------------------------------------------------------
    # Lifecycle (excluded from tools)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect to the database using asyncdb."""
        if self._connected:
            return

        await self._connect_asyncdb()
        self._connected = True
        self.logger.info(
            "%s connected to %s",
            self.__class__.__name__,
            self.database_type,
        )

        # Pre-warm metadata cache for the configured tables (fully lazy if
        # ``self.tables`` is None; missing/invalid entries are warned and
        # skipped).
        if self.tables:
            await self._warm_table_cache()

    async def stop(self) -> None:
        """Close the database connection and release resources."""
        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception as exc:
                self.logger.debug("Error closing connection: %s", exc)
            self._connection = None

        self._connected = False
        self.logger.info("%s disconnected", self.__class__.__name__)

    async def cleanup(self) -> None:
        """Alias for ``stop()``."""
        await self.stop()

    async def health_check(self) -> bool:
        """Check if the database connection is alive.

        Returns:
            ``True`` if the connection is healthy, ``False`` otherwise.
        """
        if not self._connected:
            return False
        try:
            if self._connection is not None:
                if hasattr(self._connection, "test_connection"):
                    return await self._connection.test_connection()
                return True
        except Exception as exc:
            self.logger.debug("Health check failed: %s", exc)
        return False

    # ------------------------------------------------------------------
    # Cache helpers (excluded from tools)
    # ------------------------------------------------------------------

    async def get_table_metadata(
        self,
        schema_name: str,
        table_name: str,
    ) -> Optional[TableMetadata]:
        """Retrieve cached table metadata for the given table.

        Args:
            schema_name: Schema that contains the table.
            table_name: Name of the table.

        Returns:
            ``TableMetadata`` if found, ``None`` otherwise.
        """
        if self.cache_partition is None:
            return None
        return await self.cache_partition.get_table_metadata(schema_name, table_name)

    # ------------------------------------------------------------------
    # Abstract — subclasses MUST implement
    # ------------------------------------------------------------------

    @abstractmethod
    async def search_schema(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[TableMetadata]:
        """Search for tables/columns matching *search_term*.

        Args:
            search_term: Natural-language or keyword search.
            schema_name: Restrict search to a specific schema.
            limit: Maximum results.

        Returns:
            List of matching ``TableMetadata``.
        """
        ...

    @abstractmethod
    async def execute_query(
        self,
        query: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> QueryExecutionResponse:
        """Execute a query and return results.

        Args:
            query: The query string (SQL, Flux, DSL, MQL, etc.).
            limit: Maximum rows to return.
            timeout: Query timeout in seconds.

        Returns:
            ``QueryExecutionResponse`` with results or error info.
        """
        ...

    # ------------------------------------------------------------------
    # Connection helpers (private)
    # ------------------------------------------------------------------

    async def _connect_asyncdb(self) -> None:
        """Connect using ``asyncdb.AsyncDB`` or ``asyncdb.AsyncPool``.

        When ``self.use_pool`` is True the driver's pool class is instantiated
        and ``connect()`` is called once; subsequent queries acquire/release a
        connection from the pool via :meth:`_acquire_asyncdb_connection`.
        Otherwise a single ``AsyncDB`` connection is opened.
        """
        driver = self._get_asyncdb_driver()
        params: Dict[str, Any] = {}
        if self.use_pool:
            from asyncdb import AsyncPool
            self._connection = AsyncPool(
                driver, dsn=self.dsn, params=params, **self.pool_params
            )
            await self._connection.connect()
        else:
            from asyncdb import AsyncDB
            self._connection = AsyncDB(driver, dsn=self.dsn, params=params)
            await self._connection.connection()  # pylint: disable=no-member

    @asynccontextmanager
    async def _acquire_asyncdb_connection(self) -> AsyncIterator[Any]:
        """Yield a raw driver connection, abstracting pool vs single.

        Unwraps the asyncdb driver wrapper once at the boundary via
        ``wrapper.engine()`` (alias for ``get_connection()``) so every
        downstream consumer works against the raw native connection object
        (e.g. raw ``asyncpg.Connection`` for PostgreSQL).

        Pooled mode: acquires the asyncdb wrapper, unwraps it, yields the
        raw connection, then releases the **wrapper** (not the raw conn)
        back to the pool on exit.

        Single mode: enters the driver as its own async context manager,
        unwraps the resulting wrapper, and yields the raw connection.
        """
        if self._connection is None:
            raise RuntimeError("Not connected (call start() first)")
        if self.use_pool:
            wrapper = await self._connection.acquire()
            try:
                yield wrapper.engine()  # raw asyncpg.Connection (or dialect equiv.)
            finally:
                try:
                    await self._connection.release(wrapper)  # release the WRAPPER
                except Exception as exc:  # pylint: disable=broad-except
                    self.logger.warning(
                        "Pool release failed — possible connection leak: %s", exc
                    )
        else:
            async with await self._connection.connection() as wrapper:
                yield wrapper.engine()  # raw asyncpg.Connection (or dialect equiv.)

    def _get_asyncdb_driver(self) -> str:
        """Map ``database_type`` to an asyncdb driver name.

        Override in subclasses for non-standard mappings.
        """
        _DRIVER_MAP = {
            "postgresql": "pg",
            "postgres": "pg",
            "bigquery": "bigquery",
            "influxdb": "influx",
            "elasticsearch": "elasticsearch",
            "documentdb": "motor",
            "mongodb": "motor",
        }
        return _DRIVER_MAP.get(self.database_type, self.database_type)
