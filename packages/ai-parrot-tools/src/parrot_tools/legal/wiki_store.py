"""``OntologyLegalWikiStore`` — read-only FEAT-450 wiki-namespace adapter (R16).

Exposes the legal ontology tenant (BOE norms graph, FEAT-449 Sprints 1 +
1.5/2) as a read-only wiki namespace: ``search_fts`` delegates to the
declarative ``search_articles`` pattern (TASK-2494/2496), ``neighbors``
walks the ``modifica``/``deroga``/``pertenece_a`` typed edges, and
``search_vector`` returns ``[]`` by design (R14 — no vectors anywhere).

Never provisions: the factory/``initialize()`` VERIFY the database and
the ``articulo`` collection exist and raise ``FileNotFoundError`` when
they do not (mirrors ``wiki/arango_store.py``'s ``read_only`` no-provision
connect, ``:282-330``), so an absent tenant surfaces as an "unbuilt"
namespace (``federation._skip_for``), never a silently-provisioned empty
database on someone else's server.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.schema import TenantContext
from parrot.knowledge.ontology.tenant import TenantOntologyManager
from parrot.knowledge.wiki.store import BaseWikiStore

from parrot_tools.legal.boe.queries import search_articles

logger = logging.getLogger(__name__)

_ARTICULO_COLLECTION = "articulo"
_NORMA_COLLECTION = "norma"
_EDGE_COLLECTIONS = ("modifica", "deroga", "pertenece_a")

_READ_ONLY_MESSAGE = "ontology_legal namespace is read-only"


def _summary(text: str, limit: int = 280) -> str:
    """First ``limit`` chars of ``text`` — the stub ``summary`` field."""
    return text[:limit]


def _token_count(text: str) -> int:
    """Approximate token count (``len(text) // 4``) — the stub ``token_count`` field."""
    return len(text) // 4


class OntologyLegalWikiStore(BaseWikiStore):
    """Read-only ``BaseWikiStore`` adapter over the legal ontology tenant.

    Write methods all raise ``NotImplementedError`` — this namespace is
    read-only by construction, not by convention. ``search_vector``
    returns ``[]`` (never raises — a combined search must degrade
    silently to lexical, R14).

    Args:
        arango_params: Connection params for ``AsyncDB("arangodb", ...)``.
        database: Target ArangoDB database name.
        wiki_name: Wiki name recorded/used for tenant resolution.
        read_only: Always effectively ``True`` for this adapter; kept as
            a constructor param for symmetry with the other backends.
        store: Test-injection seam — a pre-built ``OntologyGraphStore``
            (or compatible double). When provided together with ``ctx``,
            ``initialize()`` is a no-op (already "initialized").
        ctx: Test-injection seam — a pre-built ``TenantContext``.
    """

    def __init__(
        self,
        *,
        arango_params: dict[str, Any],
        database: str,
        wiki_name: str = "",
        read_only: bool = True,
        store: OntologyGraphStore | None = None,
        ctx: TenantContext | None = None,
    ) -> None:
        self._params = arango_params
        self._database = database
        self._wiki_name = wiki_name
        self._read_only = read_only
        self._store: OntologyGraphStore | None = store
        self._ctx: TenantContext | None = ctx
        self._initialized = store is not None and ctx is not None
        self._init_lock = asyncio.Lock()

    @classmethod
    def factory(
        cls,
        *,
        storage_dir: Any = None,
        wiki_name: str,
        database: str,
        arango_params: dict[str, Any],
        read_only: bool = True,
        **_: Any,
    ) -> OntologyLegalWikiStore:
        """Construct the store (registered as the ``"ontology_legal"`` backend).

        Deliberately SYNCHRONOUS and non-connecting (mirrors
        ``ArangoDBWikiStore.__init__``): both ``create_wiki_store``'s and
        ``federation.open_namespace_store``'s dispatch call this without
        ``await``. Verification (database + ``articulo`` collection
        existence, raising ``FileNotFoundError`` when absent) happens
        lazily on first use, in ``initialize()`` — the same
        deferred-connection contract every other backend follows here
        (a live network probe cannot run synchronously from a caller
        that is itself inside a running event loop).

        Args:
            storage_dir: Unused (server-hosted backend, no local dir).
            wiki_name: Wiki name.
            database: Target ArangoDB database name.
            arango_params: Connection params.
            read_only: Accepted for signature symmetry; always read-only.

        Returns:
            The constructed (not-yet-connected) store.
        """
        return cls(
            arango_params=arango_params,
            database=database,
            wiki_name=wiki_name,
            read_only=read_only,
        )

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Connect and verify the plane exists — NEVER provisions.

        Raises:
            FileNotFoundError: The database or its ``articulo``
                collection does not exist — the legal tenant was never
                built (classified as "unbuilt" by ``federation._skip_for``).
        """
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return

            from asyncdb import AsyncDB

            probe = AsyncDB("arangodb", params={**self._params, "database": "_system"})
            await probe.connection()
            try:
                databases = await probe.list_databases()
            except AttributeError:  # pragma: no cover - driver without the helper
                databases = None
            finally:
                await probe.close()
            if databases is not None and self._database not in set(databases):
                raise FileNotFoundError(
                    f"ArangoDB database {self._database!r} does not exist — "
                    "the legal tenant was never built"
                )

            client = AsyncDB("arangodb", params={**self._params, "database": self._database})
            await client.connection()
            if not await client.collection_exists(_ARTICULO_COLLECTION):
                raise FileNotFoundError(
                    f"ArangoDB database {self._database!r} has no "
                    f"{_ARTICULO_COLLECTION!r} collection — the legal tenant "
                    "was never built"
                )

            manager = TenantOntologyManager(ontology_dir=OntologyParser.get_defaults_dir())
            resolved = manager.resolve(self._wiki_name or "ontology_legal_wiki", domain="legal")
            self._ctx = TenantContext(
                tenant_id="ontology_legal",
                arango_db=self._database,
                pgvector_schema="ontology_legal",
                ontology=resolved.ontology,
            )
            self._store = OntologyGraphStore(arango_client=client)
            self._initialized = True

    async def _ensure_init(self) -> None:
        await self.initialize()

    async def close(self) -> None:
        """Close the underlying ArangoDB connection, if any."""
        if self._store is not None:
            client = getattr(self._store, "_client", None)
            if client is not None:
                await client.close()
        self._initialized = False

    # ------------------------------------------------------------------
    # Write API — all read-only refusals
    # ------------------------------------------------------------------

    async def upsert_pages(self, pages: list[Any]) -> int:
        raise NotImplementedError(_READ_ONLY_MESSAGE)

    async def add_edges(self, edges: list[tuple]) -> int:
        raise NotImplementedError(_READ_ONLY_MESSAGE)

    async def replace_source_slice(
        self, source_id: str, pages: list[Any], edges: list[tuple[str, str, str]] | None = None
    ) -> dict[str, Any]:
        raise NotImplementedError(_READ_ONLY_MESSAGE)

    async def delete_page(self, concept_id: str) -> bool:
        raise NotImplementedError(_READ_ONLY_MESSAGE)

    async def upsert_embedding(self, concept_id: str, vector: list[float], model: str = "") -> None:
        raise NotImplementedError(_READ_ONLY_MESSAGE)

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    async def get_page(
        self, concept_id: str, include_body: bool = True
    ) -> dict[str, Any] | None:
        """Fetch one article's in-force wording as of today.

        Args:
            concept_id: The ``articulo_key``.
            include_body: When ``False``, the ``body`` field is omitted.

        Returns:
            The page dict, or ``None`` when the article doesn't exist or
            has no in-force wording today (e.g. repealed).
        """
        await self._ensure_init()
        today = datetime.now(UTC).date()
        rows = await self._store.execute_traversal(
            self._ctx,
            (
                "FOR a IN @@articulo FILTER a._key == @key LIMIT 1 "
                "FOR v IN a.versions "
                "FILTER v.valid_from <= @as_of "
                "FILTER v.valid_to == null OR v.valid_to > @as_of "
                "LIMIT 1 "
                "RETURN {norma_ref: a.norma_ref, numero: a.numero, version: v}"
            ),
            bind_vars={"key": concept_id, "as_of": today.isoformat()},
            collection_binds={"@articulo": _ARTICULO_COLLECTION},
        )
        if not rows:
            return None
        row = rows[0]
        version = row["version"]
        text = version.get("text") if isinstance(version, dict) else version.text
        if text is None:
            return None
        norma_ref = row["norma_ref"]
        numero = row["numero"]
        page: dict[str, Any] = {
            "concept_id": concept_id,
            "node_id": concept_id,
            "title": f"{norma_ref} art. {numero}",
            "category": "articulo",
            "summary": _summary(text),
            "source_id": norma_ref,
            "token_count": _token_count(text),
        }
        if include_body:
            page["body"] = text
        return page

    async def list_pages(
        self,
        category: str | None = None,
        limit: int = 100,
        origin: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """List page stubs (no bodies), optionally filtered by category.

        Args:
            category: ``"articulo"``, ``"norma"``, or ``None`` (both).
            limit: Maximum rows returned (applied per category).
            origin: Unused — the BOE corpus has no ``origin`` concept.

        Returns:
            Stub dicts (no bodies).
        """
        await self._ensure_init()
        today = datetime.now(UTC).date().isoformat()
        stubs: list[dict[str, Any]] = []

        if category in (None, "articulo"):
            rows = await self._store.execute_traversal(
                self._ctx,
                (
                    "FOR a IN @@articulo "
                    "LIMIT @limit "
                    "FOR v IN a.versions "
                    "FILTER v.valid_from <= @as_of "
                    "FILTER v.valid_to == null OR v.valid_to > @as_of "
                    "LIMIT 1 "
                    "RETURN {articulo_key: a._key, norma_ref: a.norma_ref, "
                    "numero: a.numero, version: v}"
                ),
                bind_vars={"as_of": today, "limit": limit},
                collection_binds={"@articulo": _ARTICULO_COLLECTION},
            )
            for row in rows:
                version = row["version"]
                text = version.get("text") if isinstance(version, dict) else version.text
                if text is None:
                    continue
                stubs.append(
                    {
                        "concept_id": row["articulo_key"],
                        "node_id": row["articulo_key"],
                        "title": f"{row['norma_ref']} art. {row['numero']}",
                        "category": "articulo",
                        "summary": _summary(text),
                        "source_id": row["norma_ref"],
                        "token_count": _token_count(text),
                    }
                )

        if category in (None, "norma"):
            rows = await self._store.execute_traversal(
                self._ctx,
                "FOR n IN @@norma LIMIT @limit RETURN {boe_id: n._key, titulo: n.titulo}",
                bind_vars={"limit": limit},
                collection_binds={"@norma": _NORMA_COLLECTION},
            )
            for row in rows:
                titulo = row.get("titulo") or ""
                stubs.append(
                    {
                        "concept_id": row["boe_id"],
                        "node_id": row["boe_id"],
                        "title": titulo,
                        "category": "norma",
                        "summary": _summary(titulo),
                        "source_id": row["boe_id"],
                        "token_count": _token_count(titulo),
                    }
                )

        return stubs

    async def search_fts(
        self, query: str, category: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Lexical search — delegates to the ``search_articles`` pattern.

        Args:
            query: Free-form query text.
            category: Accepted for interface parity; only ``"articulo"``
                results exist, so any other value yields ``[]``.
            limit: Maximum results.

        Returns:
            Stub dicts with the shared ``{concept_id, node_id, title,
            category, summary, source_id, token_count, score}`` shape.
        """
        if category not in (None, "articulo"):
            return []
        await self._ensure_init()
        today = datetime.now(UTC).date()
        hits = await search_articles(self._store, self._ctx, query, today, limit=limit)
        stubs: list[dict[str, Any]] = []
        for hit in hits:
            text = hit.version.text
            if text is None:
                continue
            stubs.append(
                {
                    "concept_id": hit.articulo_key,
                    "node_id": hit.articulo_key,
                    "title": f"{hit.norma_ref} art. {hit.numero}",
                    "category": "articulo",
                    "summary": _summary(text),
                    "source_id": hit.norma_ref,
                    "token_count": _token_count(text),
                    "score": hit.score,
                }
            )
        return stubs

    async def search_vector(self, embedding: list[float], limit: int = 10) -> list[dict[str, Any]]:
        """Always ``[]`` — no vectors anywhere (R14). Never raises."""
        return []

    async def neighbors(
        self,
        concept_id: str,
        rel: str | None = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        """Walk the ``modifica``/``deroga``/``pertenece_a`` typed edges.

        Args:
            concept_id: Seed node id (``articulo_key`` or ``boe_id``).
            rel: Optional exact edge-collection filter (one of the three
                names above); ``None`` walks all three.
            direction: ``"out"``, ``"in"``, or ``"both"``.

        Returns:
            ``{concept_id, rel, direction}`` stubs.
        """
        await self._ensure_init()
        collections = (rel,) if rel in _EDGE_COLLECTIONS else _EDGE_COLLECTIONS
        results: list[dict[str, Any]] = []
        for collection in collections:
            if direction in ("out", "both"):
                rows = await self._store.execute_traversal(
                    self._ctx,
                    "FOR e IN @@edges FILTER e._from == @seed RETURN {target: e._to}",
                    bind_vars={"seed": concept_id},
                    collection_binds={"@edges": collection},
                )
                for row in rows:
                    results.append(
                        {"concept_id": row["target"], "rel": collection, "direction": "out"}
                    )
            if direction in ("in", "both"):
                rows = await self._store.execute_traversal(
                    self._ctx,
                    "FOR e IN @@edges FILTER e._to == @seed RETURN {target: e._from}",
                    bind_vars={"seed": concept_id},
                    collection_binds={"@edges": collection},
                )
                for row in rows:
                    results.append(
                        {"concept_id": row["target"], "rel": collection, "direction": "in"}
                    )
        return results

    async def dump_pages(self) -> list[dict[str, Any]]:
        """Every article's in-force page, WITH bodies (export path)."""
        return await self.list_pages(category="articulo", limit=1_000_000)

    async def dump_edges(self) -> list[dict[str, Any]]:
        """Every edge across all three typed edge collections (export path)."""
        await self._ensure_init()
        edges: list[dict[str, Any]] = []
        for collection in _EDGE_COLLECTIONS:
            rows = await self._store.execute_traversal(
                self._ctx,
                "FOR e IN @@edges RETURN {src: e._from, dst: e._to, rel: @rel}",
                bind_vars={"rel": collection},
                collection_binds={"@edges": collection},
            )
            edges.extend(rows)
        return edges

    async def stats(self) -> dict[str, Any]:
        """Counts: normas, articulos, total versions, in-force versions."""
        await self._ensure_init()
        today = datetime.now(UTC).date().isoformat()
        articulos = await self._store.execute_traversal(
            self._ctx,
            "FOR a IN @@articulo RETURN a.versions",
            bind_vars={},
            collection_binds={"@articulo": _ARTICULO_COLLECTION},
        )
        normas = await self._store.execute_traversal(
            self._ctx,
            "FOR n IN @@norma RETURN 1",
            bind_vars={},
            collection_binds={"@norma": _NORMA_COLLECTION},
        )
        total_versions = 0
        in_force_versions = 0
        for versions in articulos:
            versions = versions or []
            total_versions += len(versions)
            for v in versions:
                lower = v.get("valid_from") if isinstance(v, dict) else v.valid_from
                upper = v.get("valid_to") if isinstance(v, dict) else v.valid_to
                if lower is not None and lower <= today and (upper is None or upper > today):
                    in_force_versions += 1
        return {
            "normas": len(normas),
            "articulos": len(articulos),
            "total_versions": total_versions,
            "in_force_versions": in_force_versions,
        }

    # ------------------------------------------------------------------
    # Lint API — not applicable to a projected corpus
    # ------------------------------------------------------------------

    async def orphan_sources(self) -> list[str]:
        return []

    async def broken_edges(self) -> list[dict[str, Any]]:
        return []

    async def missing_bodies(self) -> list[str]:
        return []
