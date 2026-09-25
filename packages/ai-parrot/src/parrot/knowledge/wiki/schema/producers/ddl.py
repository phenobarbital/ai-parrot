"""DDL producer — fold .sql files into TableRecords with sqlglot, no database needed (FEAT-600 M3)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from parrot.bots.database.models import Completeness, TableMetadata
from parrot.bots.database.toolkits.sql import _SQLGLOT_DIALECT_MAP
from parrot.knowledge.wiki.repo_scan import file_concept_id
from parrot.knowledge.wiki.schema.models import TableRecord
from parrot.knowledge.wiki.schema.render import content_hash


def _is_blank_or_comment(text: str) -> bool:
    """Return whether a statement contains only whitespace and SQL comments."""
    without_comments = []
    index = 0
    while index < len(text):
        if text.startswith("--", index):
            newline = text.find("\n", index + 2)
            index = len(text) if newline == -1 else newline + 1
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = len(text) if end == -1 else end + 2
        else:
            without_comments.append(text[index])
            index += 1
    return not "".join(without_comments).strip()


def split_statements(sql_text: str) -> list[str]:
    """Split SQL at semicolons outside quotes and dollar-quoted bodies."""
    statements: list[str] = []
    start = 0
    index = 0
    quote: str | None = None
    dollar_tag: str | None = None
    while index < len(sql_text):
        if dollar_tag is not None:
            if sql_text.startswith(dollar_tag, index):
                index += len(dollar_tag)
                dollar_tag = None
            else:
                index += 1
            continue
        if quote is not None:
            if sql_text[index] == quote:
                if index + 1 < len(sql_text) and sql_text[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            elif sql_text[index] == "\\" and quote == '"':
                index += 2
                continue
            index += 1
            continue
        if sql_text.startswith("--", index):
            newline = sql_text.find("\n", index + 2)
            index = len(sql_text) if newline == -1 else newline + 1
            continue
        if sql_text.startswith("/*", index):
            end = sql_text.find("*/", index + 2)
            index = len(sql_text) if end == -1 else end + 2
            continue
        if sql_text[index] in {"'", '"', "`"}:
            quote = sql_text[index]
            index += 1
            continue
        if sql_text[index] == "$":
            end = sql_text.find("$", index + 1)
            if end != -1 and (end == index + 1 or sql_text[index + 1 : end].replace("_", "").isalnum()):
                dollar_tag = sql_text[index : end + 1]
                index = end + 1
                continue
        if sql_text[index] == ";":
            chunk = sql_text[start:index]
            if not _is_blank_or_comment(chunk):
                statements.append(chunk.strip())
            start = index + 1
        index += 1
    chunk = sql_text[start:]
    if not _is_blank_or_comment(chunk):
        statements.append(chunk.strip())
    return statements


def _table_key(table: exp.Table, default_schema: str) -> tuple[str, str]:
    return (table.db or default_schema, table.name)


def _fold_create(stmt: exp.Create, default_schema: str) -> TableMetadata | None:
    """Convert a CREATE TABLE or CREATE VIEW expression to metadata."""
    kind = str(stmt.args.get("kind") or "").upper()
    if kind not in {"TABLE", "VIEW"}:
        return None
    schema_node = stmt.this
    table = schema_node.this if isinstance(schema_node, exp.Schema) else schema_node
    if not isinstance(table, exp.Table):
        return None
    schema, name = _table_key(table, default_schema)
    metadata = TableMetadata(
        schema=schema,
        tablename=name,
        table_type="BASE TABLE" if kind == "TABLE" else "VIEW",
        full_name=f"{schema}.{name}",
        completeness=Completeness.FULL,
        source="ddl",
    )
    for node in schema_node.expressions if isinstance(schema_node, exp.Schema) else []:
        if isinstance(node, exp.ColumnDef):
            _add_column(metadata, node, default_schema)
        elif isinstance(node, exp.PrimaryKey):
            metadata.primary_keys.extend(column.name for column in node.expressions)
        elif isinstance(node, exp.ForeignKey):
            _add_fk(metadata, node, default_schema)
        elif isinstance(node, exp.Constraint):
            for constraint in node.expressions:
                if isinstance(constraint, exp.PrimaryKey):
                    metadata.primary_keys.extend(column.name for column in constraint.expressions)
                elif isinstance(constraint, exp.ForeignKey):
                    _add_fk(metadata, constraint, default_schema)
    return metadata


def _add_column(meta: TableMetadata, col: exp.ColumnDef, default_schema: str = "public") -> None:
    """Add a column and its inline constraints to metadata."""
    entry = {
        "name": col.name,
        "type": col.args["kind"].sql() if col.args.get("kind") else "",
        "nullable": True,
        "default": None,
        "comment": None,
    }
    for constraint in col.args.get("constraints") or []:
        kind = constraint.args.get("kind")
        if isinstance(kind, exp.PrimaryKeyColumnConstraint):
            meta.primary_keys.append(col.name)
            entry["nullable"] = False
        elif isinstance(kind, exp.NotNullColumnConstraint):
            entry["nullable"] = False
        elif isinstance(kind, exp.DefaultColumnConstraint):
            entry["default"] = kind.this.sql()
        elif isinstance(kind, exp.Reference):
            _add_inline_fk(meta, col.name, kind, default_schema)
    meta.columns.append(entry)


def _add_inline_fk(meta: TableMetadata, column: str, reference: exp.Reference, default_schema: str) -> None:
    """Add an inline REFERENCES constraint to metadata."""
    target = reference.this
    if not isinstance(target, exp.Schema) or not isinstance(target.this, exp.Table):
        return
    schema, table = _table_key(target.this, default_schema)
    if target.expressions:
        meta.foreign_keys.append(
            {"column": column, "ref_schema": schema, "ref_table": table, "ref_column": target.expressions[0].name}
        )


def _add_fk(meta: TableMetadata, fk: exp.ForeignKey, default_schema: str) -> None:
    """Add a table-level foreign key constraint to metadata."""
    reference = fk.args.get("reference")
    target = reference.this if reference is not None else None
    if not isinstance(target, exp.Schema) or not isinstance(target.this, exp.Table):
        return
    schema, table = _table_key(target.this, default_schema)
    for column, ref_column in zip(fk.expressions, target.expressions, strict=False):
        meta.foreign_keys.append(
            {"column": column.name, "ref_schema": schema, "ref_table": table, "ref_column": ref_column.name}
        )


def _fold_alter(stmt: exp.Alter, metadata: TableMetadata, default_schema: str) -> None:
    """Apply supported ALTER TABLE actions to existing metadata."""
    for action in stmt.args.get("actions") or []:
        if isinstance(action, exp.ColumnDef):
            _add_column(metadata, action, default_schema)
        elif isinstance(action, exp.Drop):
            for column in action.args.get("this") or action.args.get("expressions") or action.args.get("tables") or []:
                name = column.name if isinstance(column, (exp.Column, exp.Identifier)) else None
                if name is not None:
                    metadata.columns = [entry for entry in metadata.columns if entry["name"] != name]
                    metadata.primary_keys = [key for key in metadata.primary_keys if key != name]
                    metadata.foreign_keys = [fk for fk in metadata.foreign_keys if fk.get("column") != name]
        elif isinstance(action, exp.AddConstraint):
            for constraint in action.expressions:
                for nested in constraint.expressions if isinstance(constraint, exp.Constraint) else [constraint]:
                    if isinstance(nested, exp.PrimaryKey):
                        metadata.primary_keys.extend(column.name for column in nested.expressions)
                    elif isinstance(nested, exp.ForeignKey):
                        _add_fk(metadata, nested, default_schema)


def fold_ddl(
    files: list[Path],
    *,
    origin: str,
    dialect: str,
    root: Path,
    default_schema: str = "public",
) -> tuple[list[TableRecord], dict[str, str]]:
    """Fold SQL files into DDL-backed table records without raising on bad statements."""
    read = _SQLGLOT_DIALECT_MAP.get(dialect, dialect)
    tables: dict[tuple[str, str], TableMetadata] = {}
    defined_in: dict[tuple[str, str], list[str]] = {}
    errors: dict[str, str] = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for path in sorted(files):
        rel = str(path.relative_to(root)) if path.is_absolute() else str(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, chunk in enumerate(split_statements(text)):
            try:
                statement = sqlglot.parse_one(chunk, read=read)
            except ParseError as exc:
                errors[f"{rel}#{number}"] = str(exc).splitlines()[0][:200]
                continue
            if statement is None or isinstance(statement, exp.Command):
                continue
            if isinstance(statement, exp.Create):
                metadata = _fold_create(statement, default_schema)
                if metadata is not None:
                    key = (metadata.schema, metadata.tablename)
                    tables[key] = metadata
                    defined_in.setdefault(key, []).append(file_concept_id(rel))
            elif isinstance(statement, exp.Alter):
                table = statement.this
                if not isinstance(table, exp.Table):
                    continue
                key = _table_key(table, default_schema)
                metadata = tables.get(key)
                if metadata is None:
                    errors[f"{rel}#{number}"] = "ALTER of unknown table"
                    continue
                _fold_alter(statement, metadata, default_schema)
    records = [
        TableRecord(
            origin=origin,
            dialect=dialect,
            metadata=metadata,
            content_hash=content_hash(metadata),
            introspected_at=now,
            defined_in=sorted(set(defined_in.get(key, []))),
        )
        for key, metadata in tables.items()
    ]
    return records, errors
