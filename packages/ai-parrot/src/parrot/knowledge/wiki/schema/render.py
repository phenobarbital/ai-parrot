"""Deterministic projection of schema records into wiki pages (FEAT-600 M1)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any

import sqlglot
from sqlglot import exp

from parrot.bots.database.models import TableMetadata
from parrot.bots.database.toolkits.sql import _SQLGLOT_DIALECT_MAP
from parrot.knowledge.wiki.schema.ids import schema_concept_id, source_concept_id, table_concept_id
from parrot.knowledge.wiki.schema.models import ColumnRecord, SchemaSourceConfig, TableRecord
from parrot.knowledge.wiki.store import WikiPageRecord

VOLATILE_FIELDS: tuple[str, ...] = ("row_count", "last_accessed", "access_frequency", "avg_query_time", "loaded_at")
Edge = tuple[str, str, str, str]


def content_hash(metadata: TableMetadata) -> str:
    """Return the stable SHA-1 of metadata excluding volatile fields.

    Args:
        metadata: The database metadata to normalize.

    Returns:
        SHA-1 hexadecimal digest of its durable JSON projection.
    """
    data = {key: value for key, value in dataclasses.asdict(metadata).items() if key not in VOLATILE_FIELDS}
    encoded = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def render_ddl(record: TableRecord) -> str:
    """Render canonical CREATE TABLE SQL for the record's dialect.

    Args:
        record: Table record to project.

    Returns:
        Pretty, deterministic CREATE TABLE SQL.
    """
    metadata = record.metadata
    dialect = _SQLGLOT_DIALECT_MAP.get(record.dialect)
    columns: list[exp.ColumnDef] = []
    for column in metadata.columns:
        constraints: list[exp.ColumnConstraint] = []
        if not bool(column.get("nullable", True)):
            constraints.append(exp.ColumnConstraint(kind=exp.NotNullColumnConstraint()))
        if column.get("default") is not None:
            constraints.append(
                exp.ColumnConstraint(
                    kind=exp.DefaultColumnConstraint(this=sqlglot.parse_one(str(column["default"]), read=dialect))
                )
            )
        if column["name"] in metadata.primary_keys and len(metadata.primary_keys) == 1:
            constraints.append(exp.ColumnConstraint(kind=exp.PrimaryKeyColumnConstraint()))
        columns.append(
            exp.ColumnDef(
                this=exp.to_identifier(column["name"]),
                kind=exp.DataType.build(str(column.get("type", "TEXT")), dialect=dialect),
                constraints=constraints,
            )
        )
    if len(metadata.primary_keys) > 1:
        columns.append(exp.PrimaryKey(expressions=[exp.to_identifier(key) for key in metadata.primary_keys]))
    create = exp.Create(
        this=exp.Schema(this=exp.to_table(f"{metadata.schema}.{metadata.tablename}"), expressions=columns),
        kind="TABLE",
    )
    return create.sql(dialect=dialect, pretty=True)


def render_page(record: TableRecord) -> tuple[WikiPageRecord, list[ColumnRecord], list[Edge]]:
    """Project a table record into its page, column rows, and relation edges.

    Args:
        record: Table record to render.

    Returns:
        Page, column records, and provenance-bearing relation edges.
    """
    metadata = record.metadata
    table_id = table_concept_id(record.origin, metadata.schema, metadata.tablename)
    foreign_keys = {
        foreign_key["column"]: foreign_key for foreign_key in metadata.foreign_keys if "column" in foreign_key
    }
    columns = [
        ColumnRecord(
            table_id=table_id,
            ordinal=ordinal,
            name=column["name"],
            data_type=str(column.get("type", "")),
            nullable=bool(column.get("nullable", True)),
            default=column.get("default"),
            comment=column.get("comment"),
            is_primary_key=column["name"] in metadata.primary_keys,
            fk_target=(
                (
                    table_concept_id(
                        record.origin,
                        foreign_keys[column["name"]]["ref_schema"],
                        foreign_keys[column["name"]]["ref_table"],
                    )
                    + "."
                    + foreign_keys[column["name"]]["ref_column"]
                )
                if column["name"] in foreign_keys
                else None
            ),
        )
        for ordinal, column in enumerate(metadata.columns)
    ]
    edges: list[Edge] = [(schema_concept_id(record.origin, metadata.schema), table_id, "contains", "extracted")]
    edges.extend(
        (table_id, column.fk_target.rsplit(".", 1)[0], "references", "extracted")
        for column in columns
        if column.fk_target is not None
    )
    edges.extend((table_id, file_id, "defined_in", "extracted") for file_id in record.defined_in)
    frontmatter: dict[str, Any] = {
        "origin": record.origin,
        "dialect": record.dialect,
        "schema": metadata.schema,
        "table": metadata.tablename,
        "table_type": metadata.table_type,
        "completeness": int(metadata.completeness),
        "source": metadata.source,
        "introspected_at": record.introspected_at,
        "content_hash": record.content_hash,
        "row_count": metadata.row_count,
    }
    column_rows = ["| Name | Type | Nullable | Default | Comment |", "| --- | --- | --- | --- | --- |"]
    column_rows.extend(
        f"| {column.name} | {column.data_type} | {column.nullable} | {column.default or ''} | {column.comment or ''} |"
        for column in columns
    )
    relation_rows = [f"- {relation}: {target}" for _, target, relation, _ in edges]
    column_text = "\n".join(column_rows)
    relation_text = "\n".join(relation_rows)
    body = "\n\n".join(
        [
            json.dumps(frontmatter, sort_keys=True, default=str),
            f"## DDL\n\n{render_ddl(record)}",
            f"## Columns\n\n{column_text}",
            f"## Relations\n\n{relation_text}",
        ]
    )
    page = WikiPageRecord(
        concept_id=table_id,
        title=f"{metadata.schema}.{metadata.tablename}",
        category="table",
        summary=metadata.comment or "",
        body=body,
        source_id=f"schema:{record.origin}",
        origin="ingest",
        content_hash=record.content_hash,
    )
    return page, columns, edges


def render_source_page(cfg: SchemaSourceConfig) -> WikiPageRecord:
    """Render a source page containing configuration names but never a DSN value.

    Args:
        cfg: Source configuration to project.

    Returns:
        Source wiki page.
    """
    body = json.dumps(
        {
            "alias": cfg.alias,
            "dialect": cfg.dialect,
            "allowed_schemas": cfg.allowed_schemas,
            "dsn_env": cfg.dsn_env,
        },
        sort_keys=True,
    )
    return WikiPageRecord(
        concept_id=source_concept_id(cfg.alias),
        title=cfg.alias,
        category="source",
        body=body,
        source_id=f"schema:{cfg.alias}",
        origin="ingest",
    )


def render_schema_page(origin: str, schema: str, table_ids: list[str]) -> WikiPageRecord:
    """Render a schema page listing its tables.

    Args:
        origin: Source alias.
        schema: Database schema name.
        table_ids: Table concept IDs in the schema.

    Returns:
        Schema wiki page.
    """
    return WikiPageRecord(
        concept_id=schema_concept_id(origin, schema),
        title=f"{origin}/{schema}",
        category="schema",
        body="\n".join(f"- {table_id}" for table_id in sorted(table_ids)),
        source_id=f"schema:{origin}",
        origin="ingest",
    )
