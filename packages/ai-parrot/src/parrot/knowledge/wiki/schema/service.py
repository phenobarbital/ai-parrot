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


def _env_dsn(name: str) -> str:
    """Resolve the default DSN from its environment variable name."""
    import os

    return os.environ[name]
