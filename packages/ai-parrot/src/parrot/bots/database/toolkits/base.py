"""DatabaseToolkit — abstract base for all database toolkits.

Inherits from ``AbstractToolkit`` (auto-generates tools from public async
methods) and adds the database-specific lifecycle: connect, search schema,
execute queries, cache integration.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pydantic import BaseModel, Field

#: Regex for safe SQL identifiers (letters, digits, underscores).
_SAFE_IDENTIFIER = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

from ....tools.toolkit import AbstractToolkit
from ..cache import CachePartition
from ..models import (
    QueryExecutionResponse,
    SchemaMetadata,
    TableMetadata,
)
from ..retries import QueryRetryConfig

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
    backend: str = Field(default="asyncdb", description="'asyncdb' or 'sqlalchemy'")
    database_type: str = Field(default="postgresql")


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
        backend: str = "asyncdb",
        cache_partition: Optional[CachePartition] = None,
        retry_config: Optional[QueryRetryConfig] = None,
        database_type: str = "postgresql",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        # Connection config (lazy — no I/O in __init__)
        self.dsn = dsn
        self.allowed_schemas = allowed_schemas or ["public"]
        self.primary_schema = primary_schema or (self.allowed_schemas[0] if self.allowed_schemas else "public")
        self.backend = backend
        self.database_type = database_type

        # Cache & retry
        self.cache_partition = cache_partition
        self.retry_config = retry_config or QueryRetryConfig()

        # Connection state (populated by start())
        self._connection: Any = None
        self._engine: Any = None
        self._connected: bool = False

    # ------------------------------------------------------------------
    # Identifier safety
    # ------------------------------------------------------------------

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
        """Connect to the database.

        Uses ``asyncdb.AsyncDB`` when ``backend='asyncdb'``, or
        ``sqlalchemy.ext.asyncio.create_async_engine`` when
        ``backend='sqlalchemy'``.
        """
        if self._connected:
            return

        if self.backend == "asyncdb":
            await self._connect_asyncdb()
        elif self.backend == "sqlalchemy":
            await self._connect_sqlalchemy()
        else:
            raise ValueError(f"Unknown backend: {self.backend!r}")
        self._connected = True
        self.logger.info(
            "%s connected to %s (backend=%s)",
            self.__class__.__name__,
            self.database_type,
            self.backend,
        )

    async def stop(self) -> None:
        """Close the database connection and release resources."""
        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception as exc:
                self.logger.debug("Error closing connection: %s", exc)
            self._connection = None

        if self._engine is not None:
            try:
                await self._engine.dispose()
            except Exception as exc:
                self.logger.debug("Error disposing engine: %s", exc)
            self._engine = None

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
            if self.backend == "asyncdb" and self._connection is not None:
                # asyncdb connections usually have a test_connection method
                if hasattr(self._connection, "test_connection"):
                    return await self._connection.test_connection()
                return True
            elif self.backend == "sqlalchemy" and self._engine is not None:
                from sqlalchemy import text
                from sqlalchemy.ext.asyncio import AsyncSession
                from sqlalchemy.orm import sessionmaker

                async_session = sessionmaker(self._engine, class_=AsyncSession, expire_on_commit=False)
                async with async_session() as session:
                    await session.execute(text("SELECT 1"))
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
        """Connect using ``asyncdb.AsyncDB``."""
        from asyncdb import AsyncDB

        driver = self._get_asyncdb_driver()
        params: Dict[str, Any] = {}
        self._connection = AsyncDB(driver, dsn=self.dsn, params=params)
        await self._connection.connection()

    async def _connect_sqlalchemy(self) -> None:
        """Connect using ``sqlalchemy.ext.asyncio.create_async_engine``."""
        from sqlalchemy.ext.asyncio import create_async_engine

        sa_dsn = self._build_sqlalchemy_dsn(self.dsn)
        self._engine = create_async_engine(sa_dsn, echo=False)

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

    def _build_sqlalchemy_dsn(self, raw_dsn: str) -> str:
        """Ensure the DSN uses an async-capable SQLAlchemy driver.

        Override in subclasses for dialect-specific handling.
        """
        if raw_dsn.startswith("postgresql://"):
            return raw_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
        return raw_dsn
