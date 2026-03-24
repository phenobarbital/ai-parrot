"""
IcebergSource — DataSource subclass for Apache Iceberg tables.

On registration, prefetch_schema() loads the table metadata via the asyncdb
iceberg driver and retrieves column names and types without fetching any rows.
Row count estimation is also available for LLM size warnings.

At fetch time, supports DuckDB SQL queries (via driver.query()) or full-table
reads (via driver.to_df()). A static helper create_table_from_df() enables
the register-as-dataset workflow: write a DataFrame to a new Iceberg table,
then register it as a source.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import pandas as pd
import pyarrow as pa

from .base import DataSource
from parrot._imports import lazy_import

logger = logging.getLogger(__name__)


# Mapping from pandas dtype to PyArrow type for schema inference
_PANDAS_TO_PYARROW: Dict[str, Any] = {
    "int8": pa.int8(),
    "int16": pa.int16(),
    "int32": pa.int32(),
    "int64": pa.int64(),
    "uint8": pa.uint8(),
    "uint16": pa.uint16(),
    "uint32": pa.uint32(),
    "uint64": pa.uint64(),
    "float16": pa.float16(),
    "float32": pa.float32(),
    "float64": pa.float64(),
    "bool": pa.bool_(),
    "boolean": pa.bool_(),
    "object": pa.string(),
    "string": pa.string(),
    "datetime64[ns]": pa.timestamp("ns"),
    "datetime64[us]": pa.timestamp("us"),
    "datetime64[ms]": pa.timestamp("ms"),
    "datetime64[s]": pa.timestamp("s"),
}


def _infer_pyarrow_schema(df: pd.DataFrame) -> pa.Schema:
    """Infer a PyArrow schema from a pandas DataFrame's column dtypes.

    Args:
        df: DataFrame to infer schema from.

    Returns:
        PyArrow Schema with fields derived from DataFrame dtypes.
    """
    fields = []
    for col, dtype in df.dtypes.items():
        dtype_str = str(dtype)
        pa_type = _PANDAS_TO_PYARROW.get(dtype_str, pa.string())
        fields.append(pa.field(str(col), pa_type))
    return pa.schema(fields)


class IcebergSource(DataSource):
    """DataSource for Apache Iceberg tables via asyncdb's iceberg driver.

    On registration (via DatasetManager.add_iceberg_source), prefetch_schema()
    loads the table metadata to retrieve column names and types without
    fetching any rows.

    At fetch time, the LLM can provide a DuckDB SQL query (sql=) or omit it
    to read the full table.

    Args:
        table_id: Fully-qualified Iceberg table identifier, e.g. "demo.cities".
        name: Dataset name/identifier for this source.
        catalog_params: asyncdb iceberg driver connection params
            (uri, warehouse, catalog type, etc.). Always required.
        factory: Output factory for asyncdb queries (default "pandas").
        credentials: Optional credentials dict (passed to asyncdb driver).
        dsn: Optional DSN string (not typically used for Iceberg).
    """

    def __init__(
        self,
        table_id: str,
        name: str,
        catalog_params: Dict[str, Any],
        factory: str = "pandas",
        credentials: Optional[Dict[str, Any]] = None,
        dsn: Optional[str] = None,
    ) -> None:
        self._table_id = table_id
        self._name = name
        self._catalog_params = catalog_params
        self._factory = factory
        self._credentials = credentials
        self._dsn = dsn
        self._schema: Dict[str, str] = {}
        self._row_count_estimate: Optional[int] = None

    # ─────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────

    def _get_driver(self) -> Any:
        """Instantiate the asyncdb iceberg driver.

        Returns:
            Configured asyncdb iceberg driver instance.
        """
        iceberg_mod = lazy_import(
            "asyncdb.drivers.iceberg",
            package_name="asyncdb",
            extra="iceberg",
        )
        IcebergDriver = iceberg_mod.iceberg  # type: ignore[attr-defined]
        return IcebergDriver(params=self._catalog_params)

    # ─────────────────────────────────────────────────────────────
    # DataSource interface
    # ─────────────────────────────────────────────────────────────

    async def prefetch_schema(self) -> Dict[str, str]:
        """Load Iceberg table metadata and retrieve column→type mapping.

        Calls ``driver.load_table(table_id)`` then ``driver.schema()`` to
        get column names and types without fetching any rows.

        Returns:
            Dict mapping column_name → type string.

        Raises:
            RuntimeError: If the table cannot be loaded or schema is unavailable.
        """
        driver = self._get_driver()
        try:
            async with await driver.connection() as conn:
                await conn.load_table(self._table_id)
                self._schema = conn.schema()
        except Exception as exc:
            raise RuntimeError(
                f"IcebergSource: failed to prefetch schema for '{self._table_id}': {exc}"
            ) from exc
        logger.debug(
            "IcebergSource '%s': schema prefetched (%d columns)",
            self._table_id,
            len(self._schema),
        )
        return self._schema

    async def prefetch_row_count(self) -> Optional[int]:
        """Estimate the row count for this Iceberg table.

        Uses a DuckDB COUNT(*) query via the iceberg driver. The result is
        stored in ``self._row_count_estimate`` and surfaced to the LLM so it
        can decide whether to use aggregation queries.

        Returns:
            Estimated row count, or None if the query fails.
        """
        driver = self._get_driver()
        sql = f"SELECT COUNT(*) AS cnt FROM {self._table_id}"
        try:
            async with await driver.connection() as conn:
                await conn.load_table(self._table_id)
                result, error = await conn.query(
                    sql, table_id=self._table_id, factory=self._factory
                )
                if error:
                    logger.warning(
                        "IcebergSource: row count query failed for '%s': %s",
                        self._table_id,
                        error,
                    )
                    self._row_count_estimate = None
                elif result is not None and not result.empty:
                    self._row_count_estimate = int(result.iloc[0, 0])
                else:
                    self._row_count_estimate = None
        except Exception as exc:
            logger.warning(
                "IcebergSource: row count prefetch failed for '%s': %s",
                self._table_id,
                exc,
            )
            self._row_count_estimate = None
        return self._row_count_estimate

    async def fetch(self, **params) -> pd.DataFrame:
        """Execute a query against the Iceberg table and return a DataFrame.

        If ``sql`` is provided, executes it via ``driver.query()`` (DuckDB SQL).
        Otherwise performs a full-table read via ``driver.to_df()``.

        Args:
            **params:
                sql (str, optional): DuckDB SQL statement to execute.
                    The table can be referenced by its table_id.
                Any additional params are ignored.

        Returns:
            DataFrame with the query results.

        Raises:
            RuntimeError: If the query fails or returns no data.
        """
        sql: Optional[str] = params.get("sql")
        driver = self._get_driver()

        try:
            async with await driver.connection() as conn:
                await conn.load_table(self._table_id)

                if sql:
                    logger.info(
                        "IcebergSource('%s') executing SQL: %s",
                        self._table_id,
                        sql,
                    )
                    result, error = await conn.query(
                        sql, table_id=self._table_id, factory=self._factory
                    )
                    if error:
                        raise RuntimeError(
                            f"IcebergSource '{self._table_id}' SQL query failed: {error}"
                        )
                    return result if result is not None else pd.DataFrame()
                else:
                    logger.info(
                        "IcebergSource('%s') fetching full table",
                        self._table_id,
                    )
                    result = await conn.to_df(self._table_id, factory=self._factory)
                    return result if result is not None else pd.DataFrame()

        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"IcebergSource '{self._table_id}' fetch failed: {exc}"
            ) from exc

    def describe(self) -> str:
        """Return a human-readable description for the LLM guide.

        Returns:
            String describing the Iceberg table, column count, and catalog info.
        """
        n_cols = len(self._schema)
        catalog_type = self._catalog_params.get("type") or self._catalog_params.get(
            "catalog_type", "unknown"
        )
        desc = (
            f"Iceberg table '{self._table_id}' "
            f"(catalog: {catalog_type}, {n_cols} columns known)"
        )
        if self._row_count_estimate is not None:
            desc += f", ~{self._row_count_estimate:,} rows"
        return desc

    @property
    def cache_key(self) -> str:
        """Stable Redis cache key for this Iceberg source.

        Format: ``iceberg:{table_id}``
        """
        return f"iceberg:{self._table_id}"

    # ─────────────────────────────────────────────────────────────
    # Static helpers
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    async def create_table_from_df(
        driver: Any,
        df: pd.DataFrame,
        table_id: str,
        namespace: str = "default",
        mode: str = "append",
    ) -> None:
        """Create a new Iceberg table from a DataFrame and write the data.

        Steps:
        1. Create the namespace if it does not already exist.
        2. Infer a PyArrow schema from the DataFrame dtypes.
        3. Create the Iceberg table with the inferred schema.
        4. Write the DataFrame to the table.

        Args:
            driver: Connected asyncdb iceberg driver instance (already
                inside an ``async with await driver.connection()`` block,
                or a raw connection).
            df: DataFrame to write.
            table_id: Fully-qualified target table id, e.g. "demo.cities".
            namespace: Iceberg namespace (catalog namespace) to create the
                table in. Defaults to "default".
            mode: Write mode for the data write step. One of
                "append", "overwrite". Defaults to "append".

        Raises:
            RuntimeError: If namespace creation, table creation, or the write
                fails.
        """
        schema = _infer_pyarrow_schema(df)
        try:
            await driver.create_namespace(namespace)
        except Exception as exc:
            # Namespace may already exist — log and continue
            logger.debug(
                "IcebergSource.create_table_from_df: namespace '%s' may already exist: %s",
                namespace,
                exc,
            )

        try:
            await driver.create_table(table_id, schema=schema)
        except Exception as exc:
            raise RuntimeError(
                f"IcebergSource.create_table_from_df: failed to create table "
                f"'{table_id}': {exc}"
            ) from exc

        try:
            await driver.write(df, table_id, mode=mode)
        except Exception as exc:
            raise RuntimeError(
                f"IcebergSource.create_table_from_df: failed to write data to "
                f"'{table_id}': {exc}"
            ) from exc

        logger.info(
            "IcebergSource.create_table_from_df: wrote %d rows to '%s'",
            len(df),
            table_id,
        )
