"""ArangoDB source-manifest backend (FEAT-540 M7)."""

from __future__ import annotations

from typing import Any

from parrot.knowledge.wiki.models import SourceManifestEntry

_ARANGO_SOURCES_COLLECTION = "wiki_sources"


class ArangoSourceBackend:
    """Persist source manifest entries in the shared ArangoDB collection."""

    def __init__(self, *, arango_db: Any | None = None, arango_store: Any | None = None) -> None:
        """Create an Arango source backend with an eager or lazy connection."""
        if arango_db is None and arango_store is None:
            raise ValueError(
                "SourceCollectionManager(backend='arangodb') requires either arango_db "
                "(an already-connected connection) or arango_store "
                "(an ArangoDBWikiStore to lazily initialize)"
            )
        self._arango_db = arango_db
        self._arango_store = arango_store

    async def _resolve_arango_db(self) -> Any:
        """Return the connected ArangoDB driver, initializing a store lazily."""
        if self._arango_store is not None:
            await self._arango_store.initialize()
            return self._arango_store._db
        return self._arango_db

    async def _query(self, aql: str, bind_vars: dict[str, Any]) -> list[Any]:
        """Run an AQL query, treating Arango's empty-cursor error as empty."""
        db = await self._resolve_arango_db()
        result, error = await db.query(aql, bind_vars=bind_vars)
        if error:
            if "no data found" in str(error).lower():
                return []
            raise RuntimeError(f"ArangoDB query failed: {error}")
        return result or []

    async def _execute(self, aql: str, bind_vars: dict[str, Any]) -> list[Any]:
        """Run an AQL write statement."""
        db = await self._resolve_arango_db()
        result, error = await db.execute(aql, bind_vars=bind_vars)
        if error:
            raise RuntimeError(f"ArangoDB execute failed: {error}")
        return result or []

    @staticmethod
    def _doc_to_entry(doc: dict[str, Any]) -> SourceManifestEntry:
        """Convert a ``wiki_sources`` document into a manifest entry."""
        return SourceManifestEntry(
            source_id=doc["source_id"],
            source_uri=doc["source_uri"],
            file_hash=doc["file_hash"],
            mtime=doc["mtime"],
            ingested_at=doc["ingested_at"],
            pages_generated=doc.get("pages_generated") or [],
            status=doc.get("status", "ingested"),
            doc_metadata=doc.get("doc_metadata"),
            content_type=doc.get("content_type"),
            loader=doc.get("loader"),
            external_id=doc.get("external_id"),
        )

    @staticmethod
    def _entry_to_doc(entry: SourceManifestEntry) -> dict[str, Any]:
        """Shape one entry as a ``wiki_sources`` document.

        Persists exactly the original 12 fields (the shape every pre-FEAT-540
        ``wiki_sources`` document has), NOT ``entry.model_dump()``.  The
        triage-decision fields (``destination``, ``decision_source``,
        ``charter_version``, ``composite_score``) were never stored in
        ArangoDB and are not needed to round-trip the document, so the M7
        refactor must not silently widen the stored schema; ``_doc_to_entry``
        accordingly does not read them back.
        """
        return {
            "_key": entry.source_id,
            "source_id": entry.source_id,
            "source_uri": entry.source_uri,
            "file_hash": entry.file_hash,
            "mtime": entry.mtime,
            "ingested_at": entry.ingested_at,
            "pages_generated": entry.pages_generated,
            "status": entry.status,
            "doc_metadata": entry.doc_metadata,
            "content_type": entry.content_type,
            "loader": entry.loader,
            "external_id": entry.external_id,
        }

    async def upsert(self, entry: SourceManifestEntry) -> None:
        """Insert or update one source entry."""
        await self._execute(
            "UPSERT {_key: @key} INSERT @doc UPDATE @doc IN @@collection",
            {
                "key": entry.source_id,
                "doc": self._entry_to_doc(entry),
                "@collection": _ARANGO_SOURCES_COLLECTION,
            },
        )

    async def upsert_many(self, entries: list[SourceManifestEntry]) -> None:
        """Insert or update source entries in one statement."""
        if entries:
            await self._execute(
                "FOR doc IN @docs UPSERT {_key: doc._key} INSERT doc UPDATE doc IN @@collection",
                {
                    "docs": [self._entry_to_doc(entry) for entry in entries],
                    "@collection": _ARANGO_SOURCES_COLLECTION,
                },
            )

    async def list_sources(self) -> list[SourceManifestEntry]:
        """Return all source entries."""
        return [
            self._doc_to_entry(row)
            for row in await self._query(
                "FOR doc IN @@collection RETURN doc", {"@collection": _ARANGO_SOURCES_COLLECTION}
            )
        ]

    async def get_source(self, source_id: str) -> SourceManifestEntry | None:
        """Return one source entry by id."""
        rows = await self._query(
            "FOR doc IN @@collection FILTER doc._key == @key LIMIT 1 RETURN doc",
            {"@collection": _ARANGO_SOURCES_COLLECTION, "key": source_id},
        )
        return self._doc_to_entry(rows[0]) if rows else None

    async def remove_source(self, source_id: str) -> bool:
        """Remove one source entry."""
        rows = await self._query(
            "FOR doc IN @@collection FILTER doc._key == @key REMOVE doc IN @@collection RETURN OLD",
            {"@collection": _ARANGO_SOURCES_COLLECTION, "key": source_id},
        )
        return bool(rows)

    async def find_id_by_uri(self, source_uri: str) -> str | None:
        """Find a source id by URI."""
        rows = await self._query(
            "FOR doc IN @@collection FILTER doc.source_uri == @uri LIMIT 1 RETURN doc.source_id",
            {"@collection": _ARANGO_SOURCES_COLLECTION, "uri": source_uri},
        )
        return rows[0] if rows else None

    async def find_by_external_id(self, external_id: str) -> SourceManifestEntry | None:
        """Find one source entry by external identity."""
        rows = await self._query(
            "FOR doc IN @@collection FILTER doc.external_id == @external_id LIMIT 1 RETURN doc",
            {"@collection": _ARANGO_SOURCES_COLLECTION, "external_id": external_id},
        )
        return self._doc_to_entry(rows[0]) if rows else None

    async def find_by_uris(self, uris: list[str]) -> dict[str, SourceManifestEntry]:
        """Find tracked entries by URI."""
        if not uris:
            return {}
        rows = await self._query(
            "FOR doc IN @@collection FILTER doc.source_uri IN @uris RETURN doc",
            {"@collection": _ARANGO_SOURCES_COLLECTION, "uris": list(set(uris))},
        )
        return {entry.source_uri: entry for entry in map(self._doc_to_entry, rows)}

    async def find_by_ids(self, source_ids: list[str]) -> dict[str, SourceManifestEntry]:
        """Find tracked entries by source id."""
        if not source_ids:
            return {}
        rows = await self._query(
            "FOR doc IN @@collection FILTER doc._key IN @keys RETURN doc",
            {"@collection": _ARANGO_SOURCES_COLLECTION, "keys": list(set(source_ids))},
        )
        return {entry.source_id: entry for entry in map(self._doc_to_entry, rows)}

    async def find_by_external_ids(self, external_ids: list[str]) -> dict[str, SourceManifestEntry]:
        """Find tracked entries by external identity."""
        if not external_ids:
            return {}
        rows = await self._query(
            "FOR doc IN @@collection FILTER doc.external_id IN @ids RETURN doc",
            {"@collection": _ARANGO_SOURCES_COLLECTION, "ids": list(set(external_ids))},
        )
        return {entry.external_id: entry for entry in map(self._doc_to_entry, rows) if entry.external_id is not None}

    async def list_by_external_prefix(self, prefix: str) -> list[SourceManifestEntry]:
        """List source entries with a matching external-id prefix."""
        rows = await self._query(
            "FOR doc IN @@collection FILTER doc.external_id != null FILTER STARTS_WITH(doc.external_id, @prefix) RETURN doc",
            {"@collection": _ARANGO_SOURCES_COLLECTION, "prefix": prefix},
        )
        return [self._doc_to_entry(row) for row in rows]
