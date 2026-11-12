"""Database target for accounting queries through the shipped semantic Executor (FEAT-713 M6)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Sequence

from sqlglot import exp

from parrot.semantic.errors import SemanticExecutionError
from parrot.semantic.execution import Executor
from parrot.semantic.models import GovernedQuery

from ..errors import AccountingExecutionError
from ..evaluation import evaluate_rows
from ..models import AccountingModel, CompiledMetricQuery, RuntimeResult
from .duckdb import output_columns

#: Subject digest for system reads of the account master (no end-user subject is involved).
CHART_SUBJECT_DIGEST = "accounting:chart-master"


def _table_parts(table: str) -> tuple[str, ...]:
    """Split ``[catalog.][db.]table`` into its parts.

    Raises:
        AccountingExecutionError: Empty name, an empty part, or more than three parts.
    """
    parts = tuple(table.split("."))
    if not table or any(not part for part in parts) or len(parts) > 3:
        raise AccountingExecutionError(f"invalid table name {table!r}")
    return parts


def _table_node(table: str) -> exp.Table:
    """Table node built from quoted identifiers (the name is never parsed as SQL)."""
    parts = _table_parts(table)
    kwargs: dict[str, exp.Identifier] = {"this": exp.to_identifier(parts[-1], quoted=True)}
    if len(parts) >= 2:
        kwargs["db"] = exp.to_identifier(parts[-2], quoted=True)
    if len(parts) == 3:
        kwargs["catalog"] = exp.to_identifier(parts[0], quoted=True)
    return exp.Table(**kwargs)


class DatabaseRuntime:
    """Wraps compiled SQL in a GovernedQuery and runs it unchanged through Executor.run_with_columns."""

    def __init__(self, executor: Executor, *, result_limit: int = 10_000) -> None:
        """Bind the shipped executor and the row cap.

        Args:
            executor: The semantic-layer executor (toolkit + connection resolver).
            result_limit: Maximum number of result rows; more ⇒ ``AccountingExecutionError``.

        Raises:
            ValueError: ``result_limit`` is not positive.
        """
        if result_limit < 1:
            raise ValueError("result_limit must be positive")
        self.executor = executor
        self.result_limit = result_limit
        self.logger = logging.getLogger(__name__)

    def _source(self, driver: str) -> Any:
        """``executor.toolkit.get_source(driver)``; lookup failures ⇒ AccountingExecutionError."""
        try:
            return self.executor.toolkit.get_source(driver)
        except Exception as exc:
            self.logger.warning("accounting source lookup failed: %s", type(exc).__name__)
            raise AccountingExecutionError(f"unknown database driver {driver!r}") from exc

    def _dialect(self, driver: str) -> str:
        """sqlglot dialect of *driver*; a non-SQL source ⇒ AccountingExecutionError."""
        dialect = getattr(self._source(driver), "sqlglot_dialect", None)
        if not dialect:
            raise AccountingExecutionError(f"driver {driver!r} has no SQL dialect")
        return str(dialect)

    def dialect_for(self, model: AccountingModel) -> str:
        """The sqlglot dialect of the model's journal driver.

        Args:
            model: Model whose journal source is a database table.

        Returns:
            ``executor.toolkit.get_source(driver).sqlglot_dialect``.

        Raises:
            AccountingExecutionError: The source is a dataframe, the driver is unknown, or it has no SQL dialect.
        """
        driver = model.spec.chart_of_accounts.source.driver
        if not driver:
            raise AccountingExecutionError("database runtime needs a table source with a driver")
        return self._dialect(driver)

    async def _run(self, governed: GovernedQuery, *, connection: str) -> list[dict]:
        """Run *governed* through the executor; errors and truncation ⇒ AccountingExecutionError."""
        try:
            rows, _count, truncated, _ms, _columns = await self.executor.run_with_columns(
                governed, connection=connection
            )
        except SemanticExecutionError as exc:
            raise AccountingExecutionError(str(exc)) from exc
        if truncated:
            raise AccountingExecutionError(f"result exceeds {self.result_limit} rows; narrow the request")
        return rows

    async def execute(
        self, compiled: CompiledMetricQuery, model: AccountingModel, *, subject_digest: str
    ) -> RuntimeResult:
        """Run the compiled SQL unchanged through ``Executor.run_with_columns`` and evaluate exactly.

        Args:
            compiled: The compiled query; ``compiled.sql`` is sent byte-for-byte (no ``LIMIT`` is added).
            model: The model whose journal source is a database table.
            subject_digest: Digest of the requesting subject, supplied by the caller.

        Returns:
            Evaluated rows with exact ``Decimal`` amounts.

        Raises:
            AccountingExecutionError: Dataframe source, execution failure, or a truncated result.
        """
        chart = model.spec.chart_of_accounts
        source = chart.source
        if source.table is None or not source.driver or not source.connection:
            raise AccountingExecutionError("database runtime needs a table source with connection and driver")
        declared = (chart.account_key, chart.posting_date, chart.amount, chart.debit, chart.credit, *chart.dimensions)
        physical_columns = tuple(dict.fromkeys(column for column in declared if column))
        lineage = compiled.lineage
        governed = GovernedQuery(
            sql=compiled.sql,
            dialect=compiled.dialect,
            driver=source.driver,
            tables=(source.table,),
            rls_applied=(),
            masked_columns=(),
            limit=self.result_limit,
            subject_digest=subject_digest,
            members=((lineage.metric or f"assertion:{lineage.assertion_index}"),),
            physical_columns=physical_columns,
        )
        started = time.monotonic()
        rows = await self._run(governed, connection=source.connection)
        evaluated = await asyncio.to_thread(evaluate_rows, compiled.plan, rows)
        return RuntimeResult(
            columns=output_columns(compiled.plan),
            rows=evaluated,
            target="database",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    async def fetch_chart_rows(self, *, connection: str, driver: str, table: str, columns: Sequence[str]) -> list[dict]:
        """``SELECT DISTINCT <columns> FROM <table>`` of the account master through the executor.

        Identifiers are built as quoted sqlglot nodes; nothing is interpolated into SQL text.

        Args:
            connection: Named connection for the ConnectionResolver.
            driver: DatabaseQueryToolkit driver name.
            table: ``[catalog.][db.]table`` of the account master.
            columns: Columns to read (feeds ``snapshot_from_rows``).

        Returns:
            The distinct rows.

        Raises:
            AccountingExecutionError: No columns, invalid table, execution failure or truncation.
        """
        names = tuple(dict.fromkeys(columns))
        if not names or any(not name for name in names):
            raise AccountingExecutionError("fetch_chart_rows needs at least one non-empty column")
        dialect = self._dialect(driver)
        select = exp.Select(expressions=[exp.Column(this=exp.to_identifier(name, quoted=True)) for name in names])
        select = select.distinct(copy=False).from_(_table_node(table), copy=False)
        governed = GovernedQuery(
            sql=select.sql(dialect=dialect),
            dialect=dialect,
            driver=driver,
            tables=(table,),
            rls_applied=(),
            masked_columns=(),
            limit=self.result_limit,
            subject_digest=CHART_SUBJECT_DIGEST,
            members=(),
            physical_columns=names,
        )
        return await self._run(governed, connection=connection)

    async def fetch_columns(self, *, connection: str, driver: str, table: str) -> dict[str, str]:
        """Journal column types through ``source.get_metadata(credentials, [table])``.

        Args:
            connection: Named connection for the ConnectionResolver.
            driver: DatabaseQueryToolkit driver name.
            table: ``[db.]table`` of the journal.

        Returns:
            ``{column name: data_type}`` in metadata order.

        Raises:
            AccountingExecutionError: Unknown driver, unresolved credentials, metadata failure or missing table.
        """
        parts = _table_parts(table)
        source = self._source(driver)
        try:
            credentials = self.executor.resolver.resolve(connection, driver)
        except SemanticExecutionError as exc:
            raise AccountingExecutionError(str(exc)) from exc
        try:
            metadata = await source.get_metadata(credentials, [parts[-1]])
        except Exception as exc:
            self.logger.warning("accounting metadata lookup failed: %s", type(exc).__name__)
            raise AccountingExecutionError(f"metadata lookup failed ({type(exc).__name__})") from exc
        schema = parts[-2] if len(parts) >= 2 else None
        for meta in metadata.tables:
            if meta.name == parts[-1] and (schema is None or meta.schema_name == schema):
                return {column.name: column.data_type for column in meta.columns}
        raise AccountingExecutionError(f"table {table!r} not found on connection {connection!r}")
