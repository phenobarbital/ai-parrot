"""
DeltaTableSource — DataSource subclass for Delta Lake tables.

On registration, prefetch_schema() opens a connection via the asyncdb delta
driver and calls conn.schema() to retrieve column names and types from the
Delta table metadata without fetching any rows.

At fetch time, supports:
- DuckDB SQL queries (``sql`` param) via ``conn.query(sentence=sql, tablename=...)``
- Column selection (``columns`` param) via ``conn.to_df(columns=...)``
- Filter expressions (``filter`` param) via ``conn.query(sentence=filter_expr)``
- Full-table read (no params) via ``conn.to_df()``

Supports local paths, s3:// (with AWSInterface credential resolution), and gs://.
Row count estimation is available for LLM size warnings.

A static helper create_from_parquet() enables creating a new Delta table from
an existing Parquet file.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from .base import DataSource
from parrot._imports import lazy_import

logger = logging.getLogger(__name__)


def _is_s3_path(path: str) -> bool:
    """Return True if path points to an S3 location."""
    return path.startswith("s3://") or path.startswith("s3a://")


def _is_gcs_path(path: str) -> bool:
    """Return True if path points to a GCS location."""
    return path.startswith("gs://") or path.startswith("gcs://")


def _get_aws_storage_options() -> Optional[Dict[str, str]]:
    """Resolve AWS credentials via AWSInterface for S3 paths.

    Uses ``parrot.interfaces.aws.AWSInterface`` to look up the default
    credential set (honouring ``AWS_CREDENTIALS`` config, environment
    variables, and session tokens). The resulting keys are mapped to the
    storage-options format expected by the asyncdb delta driver / deltalake.

    Returns:
        Storage options dict with AWS credentials, or None if unavailable.
    """
    try:
        from parrot.interfaces.aws import AWSInterface

        aws = AWSInterface()
        cfg = aws.aws_config

        storage_options: Dict[str, str] = {}
        if cfg.get("aws_access_key_id"):
            storage_options["AWS_ACCESS_KEY_ID"] = cfg["aws_access_key_id"]
        if cfg.get("aws_secret_access_key"):
            storage_options["AWS_SECRET_ACCESS_KEY"] = cfg["aws_secret_access_key"]
        if cfg.get("region_name"):
            storage_options["AWS_REGION"] = cfg["region_name"]
        if cfg.get("aws_session_token"):
            storage_options["AWS_SESSION_TOKEN"] = cfg["aws_session_token"]
        return storage_options if storage_options else None
    except Exception as exc:
        logger.debug("Could not resolve AWS credentials from AWSInterface: %s", exc)
        return None


class DeltaTableSource(DataSource):
    """DataSource for Delta Lake tables via asyncdb's delta driver.

    Supports local paths, S3 (s3://), and GCS (gs://) via asyncdb's built-in
    storage support. For S3 paths, credentials are resolved via AWSInterface
    from parrot/interfaces/aws.py.

    Args:
        path: Path to the Delta table. Can be a local filesystem path,
            an S3 URI (``s3://bucket/path``), or a GCS URI
            (``gs://bucket/path``).
        name: Dataset name/identifier for this source.
        table_name: DuckDB alias used for SQL queries (e.g. in
            ``SELECT * FROM {table_name} WHERE ...``). Defaults to the
            uppercased ``name``.
        mode: Write mode for creation operations: ``overwrite``, ``append``,
            ``error``, ``ignore``. Defaults to ``"error"``.
        credentials: Optional credentials dict for cloud storage access.
            For S3, AWSInterface is used automatically when this is None.
    """

    def __init__(
        self,
        path: str,
        name: str,
        table_name: Optional[str] = None,
        mode: str = "error",
        credentials: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._path = path
        self._name = name
        self._table_name = table_name or name.upper()
        self._mode = mode
        self._credentials = credentials
        self._schema: Dict[str, str] = {}
        self._row_count_estimate: Optional[int] = None

    # ─────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────

    def _build_params(self) -> Dict[str, Any]:
        """Build asyncdb driver params dict.

        For S3 paths, merges AWSInterface credentials into storage_options
        unless explicit credentials are provided.

        Returns:
            Parameters dict for the asyncdb delta driver.
        """
        params: Dict[str, Any] = {"path": self._path}

        if self._credentials:
            params["storage_options"] = self._credentials
        elif _is_s3_path(self._path):
            aws_opts = _get_aws_storage_options()
            if aws_opts:
                params["storage_options"] = aws_opts

        return params

    def _get_driver(self) -> Any:
        """Instantiate the asyncdb delta driver.

        Returns:
            Configured asyncdb delta driver instance.
        """
        delta_mod = lazy_import(
            "asyncdb.drivers.delta",
            package_name="asyncdb",
            extra="delta",
        )
        DeltaDriver = delta_mod.delta  # type: ignore[attr-defined]
        return DeltaDriver(params=self._build_params())

    # ─────────────────────────────────────────────────────────────
    # DataSource interface
    # ─────────────────────────────────────────────────────────────

    @property
    def cache_key(self) -> str:
        """Stable Redis cache key for this Delta table source.

        Format: ``delta:{md5(path)[:12]}``
        """
        path_hash = hashlib.md5(self._path.encode()).hexdigest()[:12]
        return f"delta:{path_hash}"

    async def prefetch_schema(self) -> Dict[str, str]:
        """Retrieve column→type mapping from Delta table metadata.

        Opens a connection via the asyncdb delta driver and calls
        ``conn.schema()`` to get column names and types without fetching
        any rows.

        Returns:
            Dict mapping column_name → type string.

        Raises:
            RuntimeError: If the table cannot be opened or schema is unavailable.
        """
        driver = self._get_driver()
        try:
            async with await driver.connection() as conn:
                self._schema = conn.schema()
        except Exception as exc:
            raise RuntimeError(
                f"DeltaTableSource: failed to prefetch schema for '{self._path}': {exc}"
            ) from exc

        logger.debug(
            "DeltaTableSource '%s': schema prefetched (%d columns)",
            self._path,
            len(self._schema),
        )
        return self._schema

    async def prefetch_row_count(self) -> Optional[int]:
        """Estimate the row count for this Delta table.

        Uses a COUNT(*) SQL query. The result is stored in
        ``self._row_count_estimate``.

        Returns:
            Estimated row count, or None if the query fails.
        """
        sql = f"SELECT COUNT(*) AS cnt FROM {self._table_name}"
        driver = self._get_driver()
        try:
            async with await driver.connection() as conn:
                result, error = await conn.query(
                    sentence=sql,
                    tablename=self._table_name,
                    factory="pandas",
                )
                if error:
                    logger.warning(
                        "DeltaTableSource: row count query failed for '%s': %s",
                        self._path,
                        error,
                    )
                    self._row_count_estimate = None
                elif result is not None:
                    if isinstance(result, pd.DataFrame) and not result.empty:
                        self._row_count_estimate = int(result.iloc[0, 0])
                    elif isinstance(result, tuple) and result:
                        self._row_count_estimate = int(result[0])
                    else:
                        self._row_count_estimate = None
                else:
                    self._row_count_estimate = None
        except Exception as exc:
            logger.warning(
                "DeltaTableSource: row count prefetch failed for '%s': %s",
                self._path,
                exc,
            )
            self._row_count_estimate = None

        return self._row_count_estimate

    async def fetch(self, **params) -> pd.DataFrame:
        """Query the Delta table and return a DataFrame.

        Priority of fetch modes:
        1. ``sql`` — DuckDB SQL query via ``conn.query(sentence=sql, tablename=...)``
        2. ``columns`` — selective column fetch via ``conn.to_df(columns=...)``
        3. ``filter`` — filter expression via ``conn.query(sentence=filter_expr)``
        4. (default) full table via ``conn.to_df()``

        Args:
            **params:
                sql (str, optional): DuckDB SQL statement. The table can be
                    referenced by ``self._table_name`` (DuckDB alias).
                columns (list, optional): List of column names to select.
                filter (str, optional): SQL filter expression, e.g.
                    ``"fare_amount > 30.0"``.

        Returns:
            DataFrame with the query results.

        Raises:
            RuntimeError: If the query fails.
        """
        sql: Optional[str] = params.get("sql")
        columns: Optional[List[str]] = params.get("columns")
        filter_expr: Optional[str] = params.get("filter")

        driver = self._get_driver()
        try:
            async with await driver.connection() as conn:
                if sql:
                    logger.info(
                        "DeltaTableSource('%s') executing SQL: %s",
                        self._path,
                        sql,
                    )
                    result, error = await conn.query(
                        sentence=sql,
                        tablename=self._table_name,
                        factory="pandas",
                    )
                    if error:
                        raise RuntimeError(
                            f"DeltaTableSource '{self._path}' SQL query failed: {error}"
                        )
                    return self._extract_df(result)

                elif columns:
                    logger.info(
                        "DeltaTableSource('%s') fetching columns: %s",
                        self._path,
                        columns,
                    )
                    result, error = await conn.to_df(columns=columns, factory="pandas")
                    if error:
                        raise RuntimeError(
                            f"DeltaTableSource '{self._path}' column fetch failed: {error}"
                        )
                    return self._extract_df(result)

                elif filter_expr:
                    logger.info(
                        "DeltaTableSource('%s') applying filter: %s",
                        self._path,
                        filter_expr,
                    )
                    result, error = await conn.query(
                        sentence=filter_expr, factory="pandas"
                    )
                    if error:
                        raise RuntimeError(
                            f"DeltaTableSource '{self._path}' filter query failed: {error}"
                        )
                    return self._extract_df(result)

                else:
                    logger.info(
                        "DeltaTableSource('%s') fetching full table",
                        self._path,
                    )
                    result, error = await conn.to_df(factory="pandas")
                    if error:
                        raise RuntimeError(
                            f"DeltaTableSource '{self._path}' full-table fetch failed: {error}"
                        )
                    return self._extract_df(result)

        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"DeltaTableSource '{self._path}' fetch failed: {exc}"
            ) from exc

    @staticmethod
    def _extract_df(result: Any) -> pd.DataFrame:
        """Extract DataFrame from asyncdb result (which may be a tuple or DataFrame).

        Args:
            result: Either a ``(DataFrame, error)`` tuple or a raw DataFrame.

        Returns:
            DataFrame, or empty DataFrame if result is None.
        """
        if result is None:
            return pd.DataFrame()
        if isinstance(result, pd.DataFrame):
            return result
        # Some asyncdb drivers return (df, metadata) tuples
        if isinstance(result, tuple) and len(result) >= 1:
            df = result[0]
            return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
        return pd.DataFrame()

    def describe(self) -> str:
        """Return a human-readable description for the LLM guide.

        Returns:
            String describing the Delta table path, DuckDB alias, and column count.
        """
        n_cols = len(self._schema)
        path_display = self._path
        if len(path_display) > 60:
            path_display = "..." + path_display[-57:]
        desc = (
            f"Delta Lake table at '{path_display}' "
            f"(table_name: {self._table_name}, {n_cols} columns known)"
        )
        if self._row_count_estimate is not None:
            desc += f", ~{self._row_count_estimate:,} rows"
        return desc

    # ─────────────────────────────────────────────────────────────
    # Static helpers
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    async def create_from_parquet(
        delta_path: str,
        parquet_path: str,
        table_name: Optional[str] = None,
        mode: str = "overwrite",
        credentials: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create a Delta table from a Parquet file.

        Args:
            delta_path: Target path for the new Delta table (local, s3://, gs://).
            parquet_path: Path to the source Parquet file.
            table_name: Optional name alias for the table (used in DuckDB queries).
            mode: Write mode: ``overwrite``, ``append``, ``error``, ``ignore``.
                Defaults to ``"overwrite"``.
            credentials: Optional credentials dict for cloud storage.

        Raises:
            RuntimeError: If the Delta table creation fails.
        """
        delta_mod = lazy_import(
            "asyncdb.drivers.delta",
            package_name="asyncdb",
            extra="delta",
        )
        DeltaDriver = delta_mod.delta  # type: ignore[attr-defined]

        params: Dict[str, Any] = {"path": delta_path}
        if credentials:
            params["storage_options"] = credentials
        elif _is_s3_path(delta_path):
            aws_opts = _get_aws_storage_options()
            if aws_opts:
                params["storage_options"] = aws_opts

        driver = DeltaDriver(params=params)
        try:
            await driver.create(
                delta_path,
                parquet_path,
                name=table_name,
                mode=mode,
            )
        except Exception as exc:
            raise RuntimeError(
                f"DeltaTableSource.create_from_parquet: failed to create Delta table "
                f"at '{delta_path}' from '{parquet_path}': {exc}"
            ) from exc

        logger.info(
            "DeltaTableSource.create_from_parquet: Delta table created at '%s'",
            delta_path,
        )
