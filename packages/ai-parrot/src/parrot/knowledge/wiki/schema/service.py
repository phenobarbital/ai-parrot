"""Schema-plane application service backed by :class:`SchemaStore`."""

from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from parrot.bots.database.models import Completeness, TableMetadata
from parrot.knowledge.wiki.project import find_shared_root, load_effective_config, sqlite_policy_from_config
from parrot.knowledge.wiki.schema.ids import (
    normalize_ref,
    parse_table_id,
    schema_concept_id,
    source_concept_id,
    table_concept_id,
)
from parrot.knowledge.wiki.schema.models import (
    LookupResult,
    SchemaPlaneConfig,
    SchemaSourceConfig,
    SyncReport,
    TableRecord,
)
from parrot.knowledge.wiki.schema.producers.live import introspect
from parrot.knowledge.wiki.schema.render import content_hash, render_page, render_schema_page, render_source_page
from parrot.knowledge.wiki.schema.store import SchemaStore

logger = logging.getLogger(__name__)


class SchemaPlaneReader(Protocol):
    """Read/write surface consumed by the database cache tier."""

    async def get_table(self, origin: str, schema: str, table: str) -> Optional[TableMetadata]: ...

    async def put_table(self, origin: str, dialect: str, metadata: TableMetadata) -> None: ...

    async def list_tables(self, origin: str, schema: Optional[str] = None) -> list[str]: ...


class SchemaPlaneService:
    """Coordinate schema sync, lookup, relationship traversal, and search."""

    def __init__(
        self, store: SchemaStore, config: SchemaPlaneConfig, plane_dir: Path, shared_root: Optional[Path]
    ) -> None:
        """Initialize a service with its already-openable schema store."""
        self._store = store
        self.config = config
        self.plane_dir = plane_dir
        self.shared_root = shared_root
        self.logger = logging.getLogger(__name__)

    @classmethod
    def from_root(cls, root: Optional[Path] = None) -> "SchemaPlaneService":
        """Open the schema plane at the effective shared project root."""
        shared_root = find_shared_root(root) or (root or Path.cwd()).resolve()
        config = load_effective_config(shared_root).config
        plane_dir = config.schema_path(shared_root)
        plane_dir.mkdir(parents=True, exist_ok=True)
        store = SchemaStore(
            plane_dir / "schema.db", wiki_name="schema", sqlite_policy=sqlite_policy_from_config(config)
        )
        return cls(store, config.schema, plane_dir, shared_root)

    @classmethod
    def from_dir(
        cls,
        plane_dir: Path,
        *,
        config: Optional[SchemaPlaneConfig] = None,
        read_only: bool = True,
    ) -> "SchemaPlaneService":
        """Open a rootless schema plane without resolving a project checkout."""
        if not read_only:
            plane_dir.mkdir(parents=True, exist_ok=True)
        store = SchemaStore(plane_dir / "schema.db", wiki_name="schema", read_only=read_only)
        return cls(store, config or SchemaPlaneConfig(), plane_dir, None)

    @property
    def store(self) -> SchemaStore:
        """Return the backing schema store."""
        return self._store

    async def sync(
        self,
        origin: str,
        *,
        tables: Optional[list[str]] = None,
        changed_only: bool = False,
        dsn_resolver: Optional[Callable[[str], str]] = None,
        toolkit: Any = None,
    ) -> SyncReport:
        """Introspect an origin and persist its resulting schema slice."""
        cfg = self.config.sources[origin]
        dsn = (dsn_resolver or _env_dsn)(cfg.dsn_env)
        records, failed = await introspect(cfg, dsn, tables=tables, toolkit=toolkit)
        report = SyncReport(failed=failed)
        ids = [table_concept_id(record.origin, record.metadata.schema, record.metadata.tablename) for record in records]
        known = await self._store.page_hashes(ids)
        for record, table_id in zip(records, ids, strict=True):
            if known.get(table_id) == record.content_hash:
                report.unchanged.append(table_id)
            elif known.get(table_id) is None:
                report.created.append(table_id)
            else:
                report.updated.append(table_id)

        existing = await self._store.list_pages(category="table", limit=100_000)
        old_ids = {page["concept_id"] for page in existing if page.get("source_id") == f"schema:{origin}"}
        if tables is None:
            report.removed.extend(sorted(old_ids - set(ids)))

        changed_ids = set(report.created + report.updated)
        write_records = [
            record for record, table_id in zip(records, ids, strict=True) if not changed_only or table_id in changed_ids
        ]
        if changed_only and report.removed:
            write_records = records
        pages, columns, edges = [], [], []
        schema_tables: dict[str, list[str]] = {}
        for record in write_records:
            page, page_columns, page_edges = render_page(record)
            pages.append(page)
            columns.extend(page_columns)
            edges.extend(page_edges)
            schema_tables.setdefault(record.metadata.schema, []).append(page.concept_id)
        if not changed_only or report.removed:
            pages.insert(0, render_source_page(cfg))
            for schema, table_ids in schema_tables.items():
                schema_id = schema_concept_id(origin, schema)
                pages.append(render_schema_page(origin, schema, table_ids))
                edges.append((source_concept_id(origin), schema_id, "contains", "extracted"))

        if not changed_only or report.removed:
            await self._store.replace_schema_slice(origin, pages, columns, edges)
        elif write_records:
            await self._store.upsert_pages(pages)
            await self._store.upsert_columns(columns)
            await self._store.add_edges(edges)
        return report

    async def ingest_ddl(
        self,
        paths: list[Path],
        *,
        origin: str,
        dialect: str,
        changed_only: bool = False,
        root: Optional[Path] = None,
    ) -> SyncReport:
        """Fold SQL files into the plane, allowing DDL only to fill live-table gaps.

        Args:
            paths: SQL migration files to fold.
            origin: Source alias for the resulting table records.
            dialect: SQL dialect used to parse the files.
            changed_only: Skip DDL records whose stored content hash is unchanged.
            root: Base directory used to derive stable migration file identifiers.

        Returns:
            A report of created, updated, unchanged, and parse-error records.
        """
        from parrot.knowledge.wiki.schema.producers.ddl import fold_ddl

        base = root or self.shared_root or Path.cwd()
        records, parse_errors = fold_ddl(paths, origin=origin, dialect=dialect, root=base)
        report = SyncReport(parse_errors=parse_errors)
        for record in records:
            table_id = table_concept_id(origin, record.metadata.schema, record.metadata.tablename)
            page, columns, edges = render_page(record)
            existing = await self._store.get_page(table_id, include_body=True)
            if existing is not None and _page_source(existing) != "ddl":
                await self._store.add_edges([(src, dst, rel) for src, dst, rel, _ in edges if rel == "defined_in"])
                report.unchanged.append(table_id)
                continue
            if changed_only and existing is not None and existing.get("content_hash") == record.content_hash:
                report.unchanged.append(table_id)
                continue
            await self._store.upsert_pages([page])
            await self._store.upsert_columns(columns)
            await self._store.add_edges([(src, dst, rel) for src, dst, rel, _ in edges])
            (report.updated if existing else report.created).append(table_id)
        return report

    async def diff(self, origin: str, *, live: Optional[list[TableRecord]] = None) -> list[dict[str, Any]]:
        """Report differences between live facts and configured DDL without resolving them.

        Args:
            origin: Source alias to compare.
            live: Optional live records. When omitted, live records are rebuilt from stored pages.

        Returns:
            Difference rows containing ``table_id``, ``field``, ``live``, and ``ddl``.
        """
        from parrot.knowledge.wiki.schema.producers.ddl import fold_ddl

        cfg = self.config.sources[origin]
        base = self.shared_root or Path.cwd()
        paths = [base / path for path in cfg.ddl_paths]
        ddl_records, _parse_errors = fold_ddl(paths, origin=origin, dialect=cfg.dialect, root=base)
        if live is None:
            live = []
            pages = await self._store.list_pages(category="table", limit=100_000)
            for page in pages:
                page_id = page["concept_id"]
                page_origin, schema, table = parse_table_id(page_id)
                if page_origin != origin:
                    continue
                stored_page = await self._store.get_page(page_id)
                if stored_page is None or _page_source(stored_page) == "ddl":
                    continue
                metadata = await self.get_table(origin, schema, table)
                if metadata is None:
                    continue
                frontmatter, _ = _page_content(stored_page["body"])
                live.append(
                    TableRecord(
                        origin=origin,
                        dialect=str(frontmatter["dialect"]),
                        metadata=metadata,
                        content_hash=str(stored_page.get("content_hash", "")),
                        introspected_at=str(frontmatter["introspected_at"]),
                    )
                )

        live_by_id = {
            table_concept_id(origin, record.metadata.schema, record.metadata.tablename): record.metadata
            for record in live
        }
        ddl_by_id = {
            table_concept_id(origin, record.metadata.schema, record.metadata.tablename): record.metadata
            for record in ddl_records
        }
        differences: list[dict[str, Any]] = []
        for table_id in sorted(live_by_id.keys() | ddl_by_id.keys()):
            live_metadata = live_by_id.get(table_id)
            ddl_metadata = ddl_by_id.get(table_id)
            if live_metadata is None or ddl_metadata is None:
                differences.append(
                    {
                        "table_id": table_id,
                        "field": "table",
                        "live": _metadata_shape(live_metadata),
                        "ddl": _metadata_shape(ddl_metadata),
                    }
                )
                continue
            differences.extend(_metadata_differences(table_id, live_metadata, ddl_metadata))
        return differences

    async def lookup(self, ref: str) -> LookupResult | list[str]:
        """Look up a table using only stored schema-plane records."""
        table_id = normalize_ref(ref, sources=self.config.sources)
        if not isinstance(table_id, str):
            return table_id
        page = await self._store.get_page(table_id)
        if page is None:
            raise KeyError(table_id)
        frontmatter, ddl = _page_content(page["body"])
        relations = await self._store.neighbors(table_id)
        annotations = [item for item in relations if item["rel"] == "about"]
        relation_items = [item for item in relations if item["rel"] != "about"]
        introspected_at = datetime.fromisoformat(str(frontmatter["introspected_at"]).replace("Z", "+00:00"))
        age_days = max(0.0, (datetime.now(timezone.utc) - introspected_at).total_seconds() / 86400)
        completeness = int(frontmatter["completeness"])
        return LookupResult(
            page_id=table_id,
            frontmatter=frontmatter,
            ddl=ddl,
            columns=await self._store.columns_for(table_id),
            relations=relation_items,
            annotations=annotations,
            age_days=age_days,
            stale=age_days > self.config.stale_after_days.get(completeness, 0),
        )

    async def neighbors(self, ref: str, *, depth: int = 1, rel: Optional[str] = "references") -> list[dict[str, Any]]:
        """Traverse table relationships breadth-first to the requested depth."""
        table_id = normalize_ref(ref, sources=self.config.sources)
        if not isinstance(table_id, str) or depth < 1:
            return []
        result: list[dict[str, Any]] = []
        visited = {table_id}
        pending = deque([(table_id, 0)])
        while pending:
            source_id, current_depth = pending.popleft()
            if current_depth >= depth:
                continue
            columns = await self._store.columns_for(source_id)
            for item in await self._store.neighbors(source_id, rel=rel):
                target_id = item["concept_id"]
                pairs = [
                    (column.name, column.fk_target.rsplit(".", 1)[1])
                    for column in columns
                    if column.fk_target and column.fk_target.rsplit(".", 1)[0] == target_id
                ]
                hop = {**item, "depth": current_depth + 1, "column_pairs": pairs}
                result.append(hop)
                if target_id not in visited and target_id.startswith("table:"):
                    visited.add(target_id)
                    pending.append((target_id, current_depth + 1))
        return result

    async def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Search table pages and column names, retaining unique table hits."""
        hits = await self._store.search_fts(query, category="table", limit=limit)
        seen = {hit["concept_id"] for hit in hits}
        for column in await self._store.find_columns(name=query, limit=limit):
            if column.table_id not in seen:
                page = await self._store.get_page(column.table_id, include_body=False)
                if page is not None:
                    hits.append({**page, "column": column.name})
                    seen.add(column.table_id)
            if len(hits) >= limit:
                break
        return hits[:limit]

    async def sources(self) -> list[SchemaSourceConfig]:
        """Return configured schema sources."""
        return list(self.config.sources.values())

    async def get_table(self, origin: str, schema: str, table: str) -> Optional[TableMetadata]:
        """Rebuild stored metadata without introspecting a database."""
        table_id = table_concept_id(origin, schema, table)
        page = await self._store.get_page(table_id)
        if page is None:
            return None
        frontmatter, _ = _page_content(page["body"])
        columns = await self._store.columns_for(table_id)
        foreign_keys = []
        for column in columns:
            if column.fk_target:
                target_id, target_column = column.fk_target.rsplit(".", 1)
                _, target_schema, target_table = parse_table_id(target_id)
                foreign_keys.append(
                    {
                        "column": column.name,
                        "ref_schema": target_schema,
                        "ref_table": target_table,
                        "ref_column": target_column,
                    }
                )
        return TableMetadata(
            schema=frontmatter["schema"],
            tablename=frontmatter["table"],
            table_type=frontmatter["table_type"],
            full_name=f"{frontmatter['schema']}.{frontmatter['table']}",
            comment=page["summary"],
            columns=[
                {
                    "name": col.name,
                    "type": col.data_type,
                    "nullable": col.nullable,
                    "default": col.default,
                    "comment": col.comment,
                }
                for col in columns
            ],
            primary_keys=[col.name for col in columns if col.is_primary_key],
            foreign_keys=foreign_keys,
            row_count=frontmatter.get("row_count"),
            completeness=Completeness(int(frontmatter["completeness"])),
            source=frontmatter["source"],
        )

    async def put_table(self, origin: str, dialect: str, metadata: TableMetadata) -> None:
        """Write one metadata entry through the schema plane."""
        record = TableRecord(
            origin=origin,
            dialect=dialect,
            metadata=metadata,
            content_hash=content_hash(metadata),
            introspected_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        page, columns, edges = render_page(record)
        await self._store.upsert_pages([page])
        await self._store.upsert_columns(columns)
        await self._store.add_edges(edges)

    async def list_tables(self, origin: str, schema: Optional[str] = None) -> list[str]:
        """List stored tables for one origin, optionally narrowed to a schema."""
        pages = await self._store.list_pages(category="table", limit=100_000)
        return sorted(
            page["concept_id"]
            for page in pages
            if (parts := parse_table_id(page["concept_id"]))[0] == origin and (schema is None or parts[1] == schema)
        )


def _page_content(body: str) -> tuple[dict[str, Any], str]:
    """Extract the JSON frontmatter and DDL section from a rendered page."""
    frontmatter_text, _, remainder = body.partition("\n\n## DDL\n\n")
    ddl, _, _ = remainder.partition("\n\n## Columns\n")
    return json.loads(frontmatter_text), ddl


def _page_source(page: dict[str, Any]) -> str:
    """Read the ``source`` frontmatter key from a stored table page.

    Args:
        page: Stored table-page mapping including its rendered body.

    Returns:
        The source marker, or ``"unknown"`` if it is absent or malformed.
    """
    try:
        frontmatter, _ = _page_content(str(page.get("body", "")))
    except (json.JSONDecodeError, TypeError):
        return "unknown"
    return str(frontmatter.get("source", "unknown"))


def _metadata_shape(metadata: Optional[TableMetadata]) -> Optional[dict[str, Any]]:
    """Return the comparable portions of a table metadata record."""
    if metadata is None:
        return None
    return {
        "columns": {
            column["name"]: {"type": str(column.get("type", "")), "nullable": bool(column.get("nullable", True))}
            for column in metadata.columns
        },
        "primary_keys": sorted(metadata.primary_keys),
        "foreign_keys": _foreign_key_set(metadata),
    }


def _foreign_key_set(metadata: TableMetadata) -> list[list[str]]:
    """Normalize foreign keys into a deterministic comparable representation."""
    return [
        list(key)
        for key in sorted(
            (
                str(foreign_key.get("column", "")),
                str(foreign_key.get("ref_schema", "")),
                str(foreign_key.get("ref_table", "")),
                str(foreign_key.get("ref_column", "")),
            )
            for foreign_key in metadata.foreign_keys
        )
    ]


def _metadata_differences(
    table_id: str,
    live: TableMetadata,
    ddl: TableMetadata,
) -> list[dict[str, Any]]:
    """Compare table columns and key constraints for one live/DDL table pair."""
    differences: list[dict[str, Any]] = []
    live_columns = {column["name"]: column for column in live.columns}
    ddl_columns = {column["name"]: column for column in ddl.columns}
    for name in sorted(live_columns.keys() | ddl_columns.keys()):
        live_column = live_columns.get(name)
        ddl_column = ddl_columns.get(name)
        if live_column is None or ddl_column is None:
            differences.append(
                {"table_id": table_id, "field": f"column:{name}", "live": live_column, "ddl": ddl_column}
            )
            continue
        for field in ("type", "nullable"):
            live_value = str(live_column.get(field, "")) if field == "type" else bool(live_column.get(field, True))
            ddl_value = str(ddl_column.get(field, "")) if field == "type" else bool(ddl_column.get(field, True))
            if live_value != ddl_value:
                differences.append(
                    {"table_id": table_id, "field": f"column:{name}.{field}", "live": live_value, "ddl": ddl_value}
                )
    for field, live_value, ddl_value in (
        ("primary_keys", sorted(live.primary_keys), sorted(ddl.primary_keys)),
        ("foreign_keys", _foreign_key_set(live), _foreign_key_set(ddl)),
    ):
        if live_value != ddl_value:
            differences.append({"table_id": table_id, "field": field, "live": live_value, "ddl": ddl_value})
    return differences


def _env_dsn(name: str) -> str:
    """Resolve the default DSN from its environment variable name."""
    import os

    return os.environ[name]
