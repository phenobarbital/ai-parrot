"""Live producer — table records from SQLToolkit dialect hooks (FEAT-600 M2)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from parrot.bots.database.toolkits.bigquery import BigQueryToolkit
from parrot.bots.database.toolkits.postgres import PostgresToolkit
from parrot.bots.database.toolkits.sql import SQLToolkit
from parrot.knowledge.wiki.schema.models import SchemaSourceConfig, TableRecord
from parrot.knowledge.wiki.schema.render import content_hash

logger = logging.getLogger(__name__)

_TOOLKITS: dict[str, type[SQLToolkit]] = {
    "postgres": PostgresToolkit,
    "postgresql": PostgresToolkit,
    "bigquery": BigQueryToolkit,
}


def toolkit_for(cfg: SchemaSourceConfig, dsn: str) -> SQLToolkit:
    """Create the dialect-appropriate toolkit without connecting.

    Args:
        cfg: Declared source configuration.
        dsn: Resolved database connection string.

    Returns:
        A toolkit configured for the source dialect and allowed schemas.
    """
    toolkit_class = _TOOLKITS.get(cfg.dialect, SQLToolkit)
    return toolkit_class(
        dsn=dsn,
        allowed_schemas=list(cfg.allowed_schemas),
        primary_schema=cfg.allowed_schemas[0],
        tables=cfg.tables,
        read_only=True,
        database_type=cfg.dialect,
    )


def _targets(cfg: SchemaSourceConfig, tables: list[str] | None) -> list[tuple[str, str]]:
    """Return configured or explicit table targets as schema/table pairs.

    Args:
        cfg: Declared source configuration.
        tables: Optional explicit ``schema.table`` targets.

    Returns:
        Table targets, with unqualified names placed in the primary schema.
    """
    names = tables or cfg.tables or []
    targets: list[tuple[str, str]] = []
    for name in names:
        schema, _, table = name.rpartition(".")
        targets.append((schema or cfg.allowed_schemas[0], table))
    return targets


def _failure_message(exc: Exception, dsn: str) -> str:
    """Return an exception message without exposing a resolved DSN.

    Args:
        exc: Exception raised while introspecting a source.
        dsn: Resolved connection string that must not be stored or logged.

    Returns:
        Exception class and redacted message.
    """
    return f"{type(exc).__name__}: {str(exc).replace(dsn, '[redacted]')}"


async def introspect(
    cfg: SchemaSourceConfig,
    dsn: str,
    *,
    tables: list[str] | None = None,
    toolkit: SQLToolkit | None = None,
) -> tuple[list[TableRecord], dict[str, str]]:
    """Build full table records while tolerating individual lookup failures.

    Args:
        cfg: Declared source configuration. Only its alias is logged.
        dsn: Resolved connection string.
        tables: Optional ``schema.table`` subset.
        toolkit: Optional injected toolkit for tests.

    Returns:
        Successful table records and failures keyed by table or schema.
    """
    active_toolkit = toolkit or toolkit_for(cfg, dsn)
    targets = _targets(cfg, tables)
    failed: dict[str, str] = {}
    if not targets:
        for schema in cfg.allowed_schemas:
            try:
                metadata = await active_toolkit.search_schema("", schema_name=schema, limit=10_000)
            except Exception as exc:  # noqa: BLE001 -- one schema must not fail the sync
                failed[schema] = _failure_message(exc, dsn)
                logger.warning("schema sync %s: schema %s failed", cfg.alias, schema)
                continue
            targets.extend((item.schema, item.tablename) for item in metadata)

    records: list[TableRecord] = []
    introspected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for schema, table in targets:
        table_name = f"{schema}.{table}"
        try:
            metadata = await active_toolkit.describe_table(schema, table)
        except Exception as exc:  # noqa: BLE001 -- one table must not fail the sync
            failed[table_name] = _failure_message(exc, dsn)
            logger.warning("schema sync %s: %s failed", cfg.alias, table_name)
            continue
        if metadata is None:
            failed[table_name] = "not found"
            continue
        if table_name not in cfg.include_samples:
            metadata.sample_data = []
        records.append(
            TableRecord(
                origin=cfg.alias,
                dialect=cfg.dialect,
                metadata=metadata,
                content_hash=content_hash(metadata),
                introspected_at=introspected_at,
            )
        )
    return records, failed
