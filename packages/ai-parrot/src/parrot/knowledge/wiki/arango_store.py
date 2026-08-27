"""ArangoDBWikiStore — ArangoDB-backed retrieval plane for the LLM Wiki.

Third :class:`~parrot.knowledge.wiki.store.BaseWikiStore` backend (FEAT-400),
alongside :class:`~parrot.knowledge.wiki.store.SQLiteWikiStore` and
:class:`~parrot.knowledge.wiki.file_store.InMemoryWikiStore`. Enables a
shared, server-hosted wiki: pages, edges, embeddings, sources, and metadata
each map to an ArangoDB document collection (prefixed ``wiki_``) in a
configurable database (default ``wiki_{wiki_name}``).

An ArangoSearch view (``{wiki_name}_pages_view``) provides BM25 lexical
search over ``title``/``summary``/``body``. Vector search uses the shared
:func:`~parrot.knowledge.wiki.store.rank_by_cosine` brute-force helper over
embeddings fetched from ``wiki_embeddings`` — matching the SQLite/in-memory
backends' contract rather than a native ArangoDB vector index (out of scope
for this feature, see the spec's Non-Goals).

Connection is via ``asyncdb``'s ArangoDB driver (``AsyncDB("arangodb", ...)``,
the same driver used by
:class:`~parrot.knowledge.ontology.graph_store.OntologyGraphStore`). The
constructor is synchronous — the connection, database, collections, and
view are created lazily by :meth:`ArangoDBWikiStore.initialize`, which every
public method calls through :meth:`ArangoDBWikiStore._ensure_init`.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

from asyncdb import AsyncDB

from parrot.knowledge.wiki.store import (
    BaseWikiStore,
    WikiPageRecord,
    estimate_tokens,
    rank_by_cosine,
)

logger = logging.getLogger(__name__)

#: ArangoDB collection names (document structure defined in the spec).
PAGES_COLLECTION = "wiki_pages"
EDGES_COLLECTION = "wiki_edges"
EMBEDDINGS_COLLECTION = "wiki_embeddings"
SOURCES_COLLECTION = "wiki_sources"
META_COLLECTION = "wiki_meta"


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


#: Characters ArangoDB accepts in a ``_key`` besides letters and digits.
#: (Reference: ArangoDB "Document Keys" — everything else, notably ``/``
#: and ``~``, is rejected with ``[ERR 1221] illegal document key``;
#: verified against ArangoDB 3.12.)
_KEY_SAFE = "_-:.@()+,=;$!*'"

#: ArangoDB's hard ``_key`` limit, in bytes (255 is rejected).
_KEY_MAX_BYTES = 254

#: Separator between a truncated key and its disambiguating digest. Must
#: itself be a legal ``_key`` character and rare in real paths — ``~`` is
#: NOT legal, ``$`` is.
_KEY_DIGEST_SEP = "$"


def document_key(identity: str) -> str:
    """Derive a valid ArangoDB ``_key`` from a wiki identity string.

    Wiki identities are path-shaped (``file:src/main.py``,
    ``dir:packages/ai-parrot``) and ArangoDB rejects ``/`` — and every
    other character outside :data:`_KEY_SAFE` — in a ``_key``. Keys are
    therefore percent-encoded, which is reversible, collision-free, and
    keeps them human-readable in the ArangoDB web UI. ``%`` is itself a
    legal ``_key`` character, so the encoding needs no second escape.

    Identities whose encoding would exceed :data:`_KEY_MAX_BYTES` are
    truncated and suffixed with a SHA-1 digest of the *original*
    identity, so long paths stay unique.

    The raw identity is always stored in a regular field
    (``concept_id`` / ``src`` / ``dst``), so nothing downstream has to
    decode a key to recover it.

    Args:
        identity: Raw identity string (e.g. a page ``concept_id``).

    Returns:
        A string usable directly as an ArangoDB ``_key``.
    """
    safe = quote(identity, safe=_KEY_SAFE)
    if len(safe.encode("utf-8")) <= _KEY_MAX_BYTES:
        return safe
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]
    # Trim on a byte budget that leaves room for the "$<digest>" suffix.
    # A cut may land inside a percent escape ("...%2"); every character of
    # an escape is individually legal in a key, and the digest is what
    # guarantees uniqueness, so a partial escape is harmless.
    budget = _KEY_MAX_BYTES - len(digest) - len(_KEY_DIGEST_SEP)
    trimmed = safe.encode("utf-8")[:budget].decode("utf-8", "ignore")
    return f"{trimmed}{_KEY_DIGEST_SEP}{digest}"


def edge_key(src: str, dst: str, rel: str) -> str:
    """Derive a valid ArangoDB ``_key`` for a typed edge.

    Same contract as :func:`document_key`, applied to the composite
    ``src__dst__rel`` edge identity (which is very likely to exceed the
    key length limit, since it concatenates two page paths).

    Args:
        src: Source page ``concept_id``.
        dst: Target page ``concept_id``.
        rel: Edge relation (e.g. ``contains``, ``references``).

    Returns:
        A string usable directly as an ArangoDB ``_key``.
    """
    return document_key(f"{src}__{dst}__{rel}")


class ArangoDBWikiStore(BaseWikiStore):
    """ArangoDB-backed wiki retrieval plane.

    Uses ``asyncdb``'s ArangoDB driver for document CRUD (via AQL UPSERT)
    and ArangoSearch views for BM25 full-text search. Vector search uses
    the shared :func:`rank_by_cosine` helper over embeddings fetched from
    the ``wiki_embeddings`` collection.

    Args:
        arango_params: Connection params for ``AsyncDB("arangodb", ...)``
            (``host``, ``port``, ``username``, ``password``, ...) —
            credentials are resolved by the caller from ``ARANGODB_*``
            environment variables, never hardcoded here.
        database: Target ArangoDB database name. Defaults to
            ``wiki_{wiki_name}``.
        wiki_name: Wiki name, used for the default database name and the
            ArangoSearch view name (``{wiki_name}_pages_view``).
        text_analyzer: ArangoSearch text analyzer(s) for the pages view.
            Accepts one name (``"text_en"``) or a comma-separated list
            (``"text_en,text_es"``) to index and search the same fields
            under several language analyzers at once — see
            :attr:`ArangoDBWikiStore.analyzers`.

    Example::

        store = ArangoDBWikiStore(
            {"host": "127.0.0.1", "port": 8529, "username": "root", "password": ""},
            wiki_name="my-wiki",
        )
        await store.initialize()
        await store.upsert_pages([WikiPageRecord(concept_id="intro", ...)])
        hits = await store.search_fts("neural networks", limit=5)
        await store.close()
    """

    def __init__(
        self,
        arango_params: dict[str, Any],
        database: str = "",
        wiki_name: str = "",
        text_analyzer: str = "text_en",
        *,
        read_only: bool = False,
    ) -> None:
        self._params = arango_params
        self._wiki_name = wiki_name
        self._database = database or f"wiki_{wiki_name or 'codebase'}"
        self._text_analyzer = text_analyzer
        self._read_only = read_only
        self._db: Optional[Any] = None
        self._initialized = False
        self._init_lock = asyncio.Lock()
        # The event loop the live connection belongs to (see
        # _connection_is_stale). Recorded when the connection is made, NOT
        # at construction: the two are rarely the same loop.
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.logger = logging.getLogger(__name__)

    @property
    def database(self) -> str:
        """Name of the ArangoDB database this store connects to."""
        return self._database

    @property
    def read_only(self) -> bool:
        """Whether this store was opened strictly for reading."""
        return self._read_only

    def _assert_writable(self) -> None:
        """Refuse a write on a store opened with ``read_only=True``.

        Raises:
            PermissionError: When the store is read-only.
        """
        if self._read_only:
            raise PermissionError(f"read-only wiki store: arangodb database {self._database!r}")

    @property
    def _view_name(self) -> str:
        """Name of the ArangoSearch view backing :meth:`search_fts`."""
        return f"{self._wiki_name}_pages_view"

    @property
    def analyzers(self) -> list[str]:
        """The ArangoSearch analyzers this store indexes and searches with.

        ``text_analyzer`` may name a single analyzer (``"text_en"``) or a
        comma-separated list (``"text_en,text_es"``). A list makes the
        pages view index ``title``/``summary``/``body`` under every listed
        analyzer, and makes :meth:`search_fts` match a query under each of
        them — so a Spanish query finds Spanish text and an English query
        finds English text, against one corpus.

        Order is preserved and duplicates are dropped, so the view's link
        definition is stable across restarts (which is what
        :meth:`_create_pages_view` compares against to decide whether the
        view needs updating).

        Returns:
            Analyzer names, at least one (falls back to ``text_en``).
        """
        seen: dict[str, None] = {}
        for name in self._text_analyzer.split(","):
            name = name.strip()
            if name:
                seen.setdefault(name, None)
        return list(seen) or ["text_en"]

    @property
    def _view_ref(self) -> str:
        """The view name quoted for interpolation into an AQL collection slot.

        ``wiki_name`` comes from the repo/project name and routinely
        contains dashes (``navigator-agent-server``). Unquoted, AQL parses
        those as subtraction and the query fails with ``[ERR 1501] SEARCH
        condition used on non-view``, so the name is always backtick-quoted.
        """
        return f"`{self._view_name}`"

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Connect to ArangoDB and create the database/collections/view.

        Idempotent — safe to call multiple times (guarded by an
        ``asyncio.Lock`` plus an ``_initialized`` flag). The target
        database is created automatically by the driver's own
        ``connection()`` on first connect.

        With ``read_only=True`` (a federated namespace, FEAT-450) this
        **verifies instead of provisioning**: nothing is created, and a
        database or page collection that does not exist raises
        :class:`FileNotFoundError` so the caller can report the
        namespace as unbuilt rather than silently standing up an empty
        one on someone else's server.

        Raises:
            FileNotFoundError: ``read_only`` and the plane does not exist.
        """
        # Checked before the `_initialized` short-circuit so EVERY entry
        # point (public methods via _ensure_init, and callers that await
        # initialize() directly — the sources manager, the federation)
        # gets a live connection rather than one bound to a dead loop.
        if self._connection_is_stale():
            await self._discard_connection()
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            if self._read_only:
                await self._connect_existing()
                self._loop = asyncio.get_running_loop()
                self._initialized = True
                return
            self._db = AsyncDB("arangodb", params={**self._params, "database": self._database})
            await self._db.connection()

            for name, is_edge in (
                (PAGES_COLLECTION, False),
                (EDGES_COLLECTION, True),
                (EMBEDDINGS_COLLECTION, False),
                (SOURCES_COLLECTION, False),
                (META_COLLECTION, False),
            ):
                if not await self._db.collection_exists(name):
                    await self._db.create_collection(name, edge=is_edge)

            await self._create_pages_view()
            self._loop = asyncio.get_running_loop()
            self._initialized = True

    async def _connect_existing(self) -> None:
        """Connect to an already-built plane without creating anything.

        Connecting straight to the target database would create it (the
        driver's ``connection()`` provisions on demand), so existence is
        checked from the ``_system`` database first.

        Raises:
            FileNotFoundError: The database or its pages collection is
                absent — the plane was never built.
        """
        probe = AsyncDB("arangodb", params={**self._params, "database": "_system"})
        await probe.connection()
        try:
            databases = await probe.list_databases()
        except AttributeError:  # pragma: no cover - driver without the helper
            databases = None
        finally:
            await probe.close()
        if databases is not None and self._database not in set(databases):
            raise FileNotFoundError(f"ArangoDB database {self._database!r} does not exist")

        self._db = AsyncDB("arangodb", params={**self._params, "database": self._database})
        await self._db.connection()
        if not await self._db.collection_exists(PAGES_COLLECTION):
            raise FileNotFoundError(
                f"ArangoDB database {self._database!r} has no"
                f" {PAGES_COLLECTION} collection — the wiki was never built"
            )

    @property
    def _view_properties(self) -> dict[str, Any]:
        """Link definition the pages view should have.

        Indexes ``title``/``summary``/``body`` under every analyzer in
        :attr:`analyzers`, so one corpus is searchable through all of them.
        """
        return {
            "links": {
                PAGES_COLLECTION: {
                    "analyzers": list(self.analyzers),
                    "fields": {"title": {}, "summary": {}, "body": {}},
                }
            }
        }

    async def _create_pages_view(self) -> None:
        """Create the ArangoSearch pages view, or update a stale one.

        Also reconciles an EXISTING view whose analyzer set no longer
        matches :attr:`analyzers` — otherwise adding a language to
        ``text_analyzer`` would silently do nothing on any wiki that had
        already been built, since the view is only ever created once.
        ArangoSearch re-indexes the linked fields itself when a link
        changes, so no re-ingest is needed.

        Drives the underlying ``arangoasync.database.Database`` directly
        (via ``self._db._connection``) instead of going through the
        installed ``asyncdb`` driver's own
        ``arangodb.create_arangosearch_view()`` wrapper: that wrapper
        calls ``self._connection.views()`` and
        ``self._connection.create_view()`` WITHOUT ``await``ing them,
        even though both are ``async def`` on ``arangoasync``'s
        ``Database`` (verified directly against the installed package —
        ``inspect.iscoroutinefunction`` is ``True`` for both). Calling
        the wrapper as documented therefore raises
        ``TypeError: 'coroutine' object is not iterable`` against any
        real server. This is a bug in the vendored dependency, not a
        supported/documented alternate call shape — worked around here
        rather than silently reproducing it.
        """
        connection = self._db._connection
        existing_views = await connection.views()
        if not any(v.get("name") == self._view_name for v in existing_views):
            await connection.create_view(
                name=self._view_name,
                view_type="arangosearch",
                properties=self._view_properties,
            )
            return

        if await self._view_analyzers_match(connection):
            return
        self.logger.info(
            "Updating ArangoSearch view %s to analyzers %s",
            self._view_name,
            self.analyzers,
        )
        await connection.replace_view(self._view_name, self._view_properties)

    async def _view_analyzers_match(self, connection: Any) -> bool:
        """Whether the live view already indexes pages with :attr:`analyzers`.

        Args:
            connection: The underlying ``arangoasync`` database.

        Returns:
            ``True`` when the view's ``wiki_pages`` link lists exactly the
            configured analyzers (order-insensitive). ``True`` as well when
            the properties cannot be read — a failed probe should not send
            every ``initialize()`` into a needless view rewrite.
        """
        try:
            info = await connection.view_info(self._view_name)
        except Exception as exc:  # noqa: BLE001 — probe only, see docstring
            self.logger.warning(
                "Could not read properties of view %s (%s); leaving it as is",
                self._view_name,
                exc,
            )
            return True
        link = (info.get("links") or {}).get(PAGES_COLLECTION) or {}
        return set(link.get("analyzers") or []) == set(self.analyzers)

    async def close(self) -> None:
        """Close the underlying ArangoDB connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None
        self._initialized = False
        self._loop = None

    def _connection_is_stale(self) -> bool:
        """Whether the cached connection belongs to a finished/foreign loop.

        ``asyncdb``'s ArangoDB driver is ``aiohttp``-backed, and aiohttp
        binds its connector to the loop that created it: a connection
        cannot outlive the ``asyncio.run(...)`` that opened it, nor be
        driven from a different loop. A process that makes several
        ``asyncio.run`` calls — the CLI's ``status``, which resolves each
        federated plane in its own run — would otherwise reuse a
        connection whose loop is closed, surfacing from deep inside the
        driver as the unhelpful ``Event loop is closed``.

        Returns:
            ``True`` when the live connection must be discarded and
            re-established on the current loop.
        """
        if not self._initialized or self._loop is None:
            return False
        if self._loop.is_closed():
            return True
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - initialize() always has one
            return False
        return current is not self._loop

    async def _discard_connection(self) -> None:
        """Drop the cached connection without driving its dead loop.

        ``close()`` is attempted but its failure is expected and ignored:
        the loop that owns the transport is exactly what is gone. The
        ``asyncio.Lock`` is rebuilt for the same reason — it binds to the
        loop that first awaits it.
        """
        db, self._db = self._db, None
        self._initialized = False
        self._loop = None
        self._init_lock = asyncio.Lock()
        if db is None:
            return
        try:
            await db.close()
        except Exception as exc:  # noqa: BLE001 — the owning loop is gone
            self.logger.debug("Ignoring close() on a stale ArangoDB connection: %s", exc)

    async def _ensure_init(self) -> None:
        """Lazily connect on first use — every public method calls this.

        Delegates to :meth:`initialize`, which is idempotent AND
        re-establishes a connection left behind by a finished event loop.
        """
        await self.initialize()

    # ------------------------------------------------------------------
    # Internal AQL helpers
    # ------------------------------------------------------------------

    async def _query(self, aql: str, bind_vars: dict[str, Any]) -> list[Any]:
        """Run a read AQL query, treating an empty result as ``[]``.

        ``asyncdb``'s ``arangodb.query()`` internally raises
        ``NoDataFound`` when the cursor yields zero rows and surfaces it
        as a non-``None`` ``error`` string — a normal empty-result
        outcome for most of this store's read paths (missing page, no
        search hits, no neighbors, ...), so it is treated as ``[]`` here
        instead of propagated as a failure. Any other error is a real
        backend failure and is raised.
        """
        result, error = await self._db.query(aql, bind_vars=bind_vars)
        if error:
            if "no data found" in str(error).lower():
                return []
            raise RuntimeError(f"ArangoDB query failed: {error}")
        return result or []

    async def _execute(self, aql: str, bind_vars: dict[str, Any]) -> list[Any]:
        """Run a write AQL statement (UPSERT/UPDATE/REMOVE)."""
        result, error = await self._db.execute(aql, bind_vars=bind_vars)
        if error:
            raise RuntimeError(f"ArangoDB execute failed: {error}")
        return result or []

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:
        """Insert or update wiki pages via AQL UPSERT.

        Args:
            pages: Page records to write.

        Returns:
            Number of pages written.
        """
        if not pages:
            return 0
        self._assert_writable()
        await self._ensure_init()
        now = _now_iso()
        docs = [
            {
                "_key": document_key(p.concept_id),
                "concept_id": p.concept_id,
                "node_id": p.node_id,
                "title": p.title,
                "category": p.category,
                "summary": p.summary,
                "body": p.body,
                "source_id": p.source_id,
                "token_count": p.token_count or estimate_tokens(p.body),
                "origin": p.origin,
                "asserted_by": p.asserted_by,
                "created_at": now,
                "updated_at": p.updated_at or now,
            }
            for p in pages
        ]
        aql = (
            "FOR doc IN @docs "
            "UPSERT {_key: doc._key} "
            "INSERT doc "
            "UPDATE {"
            "node_id: doc.node_id, title: doc.title, category: doc.category, "
            "summary: doc.summary, body: doc.body, source_id: doc.source_id, "
            "token_count: doc.token_count, updated_at: doc.updated_at, "
            "origin: doc.origin, asserted_by: doc.asserted_by"
            "} "
            "IN @@collection"
        )
        await self._execute(aql, {"docs": docs, "@collection": PAGES_COLLECTION})
        return len(pages)

    async def add_edges(self, edges: list[tuple]) -> int:
        """Insert typed edges via AQL UPSERT.

        Args:
            edges: ``(src, dst, rel)`` or ``(src, dst, rel, provenance)``
                tuples; a missing provenance defaults to ``'extracted'``.

        Returns:
            Number of edges written.
        """
        if not edges:
            return 0
        self._assert_writable()
        await self._ensure_init()
        docs = []
        for e in edges:
            src, dst, rel = e[0], e[1], e[2]
            provenance = e[3] if len(e) > 3 else "extracted"
            docs.append(
                {
                    "_key": edge_key(src, dst, rel),
                    "_from": f"{PAGES_COLLECTION}/{document_key(src)}",
                    "_to": f"{PAGES_COLLECTION}/{document_key(dst)}",
                    "src": src,
                    "dst": dst,
                    "rel": rel,
                    "provenance": provenance,
                }
            )
        aql = "FOR doc IN @docs " "UPSERT {_key: doc._key} " "INSERT doc " "UPDATE doc " "IN @@collection"
        await self._execute(aql, {"docs": docs, "@collection": EDGES_COLLECTION})
        return len(edges)

    async def replace_source_slice(
        self,
        source_id: str,
        pages: list[WikiPageRecord],
        edges: Optional[list[tuple[str, str, str]]] = None,
    ) -> dict[str, Any]:
        """Atomically replace all pages/edges derived from one source.

        Deletes existing pages whose ``source_id`` matches (plus their
        embeddings and any edges touching them), then inserts the
        replacements. Incoming edges from OTHER sources are preserved
        when the replacement re-inserts the same stable ``concept_id`` —
        matching :meth:`SQLiteWikiStore.replace_source_slice`'s contract.

        Args:
            source_id: Source whose derived pages are being replaced.
            pages: Replacement page records.
            edges: Optional replacement ``(src, dst, rel)`` edges.

        Returns:
            ``{"pages_deleted": N, "pages_written": M, "edges_written": K}``
        """
        self._assert_writable()
        await self._ensure_init()
        edges = edges or []
        new_ids = {page.concept_id for page in pages}
        # Both projections are needed: the raw ``concept_id`` to match the
        # edge collection's ``src``/``dst`` fields, and the ``_key`` to
        # address documents in REMOVE (which resolves a bare string as a
        # key, and keys are encoded — see document_key()).
        old_rows = await self._query(
            "FOR doc IN @@collection FILTER doc.source_id == @source_id" " RETURN {cid: doc.concept_id, key: doc._key}",
            {"@collection": PAGES_COLLECTION, "source_id": source_id},
        )
        old_ids = [row["cid"] for row in old_rows]
        old_keys = [row["key"] for row in old_rows]

        preserved: list[tuple[str, str, str]] = []
        if old_ids:
            old_set = set(old_ids)
            rows = await self._query(
                "FOR e IN @@collection FILTER e.dst IN @old_ids" " RETURN {src: e.src, dst: e.dst, rel: e.rel}",
                {"@collection": EDGES_COLLECTION, "old_ids": old_ids},
            )
            preserved = [
                (r["src"], r["dst"], r["rel"]) for r in rows if r["src"] not in old_set and r["dst"] in new_ids
            ]
            await self._execute(
                "FOR key IN @old_keys REMOVE key IN @@collection" " OPTIONS {ignoreErrors: true}",
                {"old_keys": old_keys, "@collection": EMBEDDINGS_COLLECTION},
            )
            await self._execute(
                "FOR e IN @@collection FILTER e.src IN @old_ids OR e.dst IN @old_ids" " REMOVE e IN @@collection",
                {"old_ids": old_ids, "@collection": EDGES_COLLECTION},
            )
            await self._execute(
                "FOR key IN @old_keys REMOVE key IN @@collection",
                {"old_keys": old_keys, "@collection": PAGES_COLLECTION},
            )

        written = await self.upsert_pages(pages)
        if edges:
            await self.add_edges(edges)
        if preserved:
            await self.add_edges(preserved)

        self.logger.debug(
            "replace_source_slice: source=%s deleted=%d written=%d",
            source_id,
            len(old_ids),
            len(pages),
        )
        return {
            "pages_deleted": len(old_ids),
            "pages_written": written,
            "edges_written": len(edges),
        }

    async def delete_page(self, concept_id: str) -> bool:
        """Delete a page and its embeddings/edges.

        Args:
            concept_id: Page identity to delete.

        Returns:
            ``True`` when a page document was actually deleted.
        """
        self._assert_writable()
        await self._ensure_init()
        key = document_key(concept_id)
        deleted_rows = await self._query(
            "FOR doc IN @@collection FILTER doc._key == @key" " REMOVE doc IN @@collection RETURN OLD",
            {"@collection": PAGES_COLLECTION, "key": key},
        )
        if not deleted_rows:
            return False
        await self._execute(
            "REMOVE @key IN @@collection OPTIONS {ignoreErrors: true}",
            {"key": key, "@collection": EMBEDDINGS_COLLECTION},
        )
        # ``src``/``dst`` hold raw concept ids, not keys.
        await self._execute(
            "FOR e IN @@collection FILTER e.src == @cid OR e.dst == @cid" " REMOVE e IN @@collection",
            {"cid": concept_id, "@collection": EDGES_COLLECTION},
        )
        return True

    async def upsert_embedding(self, concept_id: str, vector: list[float], model: str = "") -> None:
        """Store (or replace) the embedding vector for a page.

        Args:
            concept_id: Page the vector belongs to.
            vector: Embedding as a list of floats.
            model: Identifier of the embedding model used.
        """
        self._assert_writable()
        await self._ensure_init()
        key = document_key(concept_id)
        doc = {
            "_key": key,
            "concept_id": concept_id,
            "vector": list(vector),
            "model": model,
        }
        await self._execute(
            "UPSERT {_key: @key} INSERT @doc UPDATE @doc IN @@collection",
            {"key": key, "doc": doc, "@collection": EMBEDDINGS_COLLECTION},
        )

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]:
        """Fetch a single page by ``concept_id`` (falls back to ``node_id``).

        Args:
            concept_id: Stable page identity — a volatile PageIndex
                ``node_id`` is also accepted, for parity with the other
                backends.
            include_body: When ``False`` the body field is omitted.

        Returns:
            Page dict, or ``None`` when not found.
        """
        await self._ensure_init()
        fields = [
            "concept_id",
            "node_id",
            "title",
            "category",
            "summary",
            "source_id",
            "token_count",
            "created_at",
            "updated_at",
            "origin",
            "asserted_by",
        ]
        if include_body:
            fields.append("body")
        projection = ", ".join(f"{f}: doc.{f}" for f in fields)
        aql = (
            "FOR doc IN @@collection "
            "FILTER doc._key == @key OR doc.node_id == @cid "
            "LIMIT 1 "
            f"RETURN {{{projection}}}"
        )
        rows = await self._query(
            aql,
            {
                "@collection": PAGES_COLLECTION,
                "key": document_key(concept_id),
                "cid": concept_id,
            },
        )
        return rows[0] if rows else None

    async def list_pages(
        self,
        category: Optional[str] = None,
        limit: int = 100,
        origin: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """List page stubs (no bodies), optionally filtered.

        Args:
            category: Exact category pre-filter.
            limit: Maximum rows returned.
            origin: Optional origin filter, e.g. ``["memory", "authored"]``.

        Returns:
            Stub dicts ordered by ``updated_at`` (newest first).
        """
        await self._ensure_init()
        filters: list[str] = []
        bind_vars: dict[str, Any] = {"@collection": PAGES_COLLECTION, "limit": limit}
        if category is not None:
            filters.append("doc.category == @category")
            bind_vars["category"] = category
        if origin:
            filters.append("doc.origin IN @origin")
            bind_vars["origin"] = origin
        filter_clause = ("FILTER " + " AND ".join(filters)) if filters else ""
        aql = (
            "FOR doc IN @@collection "
            f"{filter_clause} "
            "SORT doc.updated_at DESC LIMIT @limit "
            "RETURN {concept_id: doc.concept_id, node_id: doc.node_id,"
            " title: doc.title, category: doc.category, summary: doc.summary,"
            " source_id: doc.source_id, token_count: doc.token_count,"
            " updated_at: doc.updated_at, origin: doc.origin,"
            " asserted_by: doc.asserted_by}"
        )
        return await self._query(aql, bind_vars)

    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]:
        """BM25 lexical search over title/summary/body via ArangoSearch.

        Matches the query under every analyzer in :attr:`analyzers`, so a
        store configured with ``"text_en,text_es"`` answers Spanish and
        English queries against the same corpus.

        Args:
            query: Free-form natural-language query.
            category: Optional exact category pre-filter.
            limit: Maximum results.

        Returns:
            Stub dicts with a ``score`` key (BM25, higher is better).
        """
        await self._ensure_init()
        # One ANALYZER() clause per configured analyzer, OR-ed together: a
        # term only matches under the analyzer that produced its tokens, so
        # searching a bilingual corpus means asking each one. Analyzer names
        # cannot be bind variables inside ANALYZER()/TOKENS(), hence the
        # numbered bind vars built here (never the raw names interpolated).
        bind_vars: dict[str, Any] = {"query": query, "limit": limit}
        clauses = []
        for index, analyzer in enumerate(self.analyzers):
            key = f"analyzer{index}"
            bind_vars[key] = analyzer
            clauses.append(
                f"ANALYZER(doc.title IN TOKENS(@query, @{key}) OR"
                f" doc.summary IN TOKENS(@query, @{key}) OR"
                f" doc.body IN TOKENS(@query, @{key}), @{key})"
            )
        search_expr = " OR ".join(clauses)
        filter_clause = "FILTER doc.category == @category" if category is not None else ""
        aql = (
            f"FOR doc IN {self._view_ref} "
            f"SEARCH {search_expr} "
            f"{filter_clause} "
            "SORT BM25(doc) DESC LIMIT @limit "
            "RETURN {concept_id: doc.concept_id, node_id: doc.node_id,"
            " title: doc.title, category: doc.category, summary: doc.summary,"
            " source_id: doc.source_id, token_count: doc.token_count,"
            " score: BM25(doc)}"
        )
        if category is not None:
            bind_vars["category"] = category
        return await self._query(aql, bind_vars)

    async def search_vector(self, embedding: list[float], limit: int = 10) -> list[dict[str, Any]]:
        """Cosine-similarity search over stored page embeddings.

        Fetches every embedding + its page stub via AQL, then delegates
        ranking to the shared :func:`rank_by_cosine` helper (brute-force
        in-process scan — appropriate at wiki scale, and keeps parity
        with the SQLite/in-memory backends rather than a native ArangoDB
        vector index).

        Args:
            embedding: Query vector.
            limit: Maximum results.

        Returns:
            Stub dicts with a ``score`` key in [-1, 1] (cosine).
        """
        await self._ensure_init()
        aql = (
            "FOR e IN @@embeddings "
            "LET p = DOCUMENT(@@pages, e.concept_id) "
            "FILTER p != null "
            "RETURN {stub: {concept_id: p.concept_id, node_id: p.node_id,"
            " title: p.title, category: p.category, summary: p.summary,"
            " source_id: p.source_id, token_count: p.token_count},"
            " vector: e.vector}"
        )
        rows = await self._query(aql, {"@embeddings": EMBEDDINGS_COLLECTION, "@pages": PAGES_COLLECTION})
        candidates: list[tuple[dict[str, Any], list[float]]] = [(row["stub"], row["vector"]) for row in rows]
        return rank_by_cosine(embedding, candidates, limit=limit)

    async def neighbors(
        self,
        concept_id: str,
        rel: Optional[str] = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        """Return edge-adjacent pages/targets of a concept.

        Args:
            concept_id: Seed page identity.
            rel: Optional exact relation filter.
            direction: ``"out"``, ``"in"``, or ``"both"``.

        Returns:
            Dicts with ``concept_id``, ``rel``, ``direction`` and — when
            the target is a known page — its stub fields.
        """
        await self._ensure_init()
        edge_directions: list[tuple[str, str, str]] = []
        if direction in ("out", "both"):
            edge_directions.append(("src", "dst", "out"))
        if direction in ("in", "both"):
            edge_directions.append(("dst", "src", "in"))

        results: list[dict[str, Any]] = []
        for anchor, other, dir_label in edge_directions:
            filters = [f"e.{anchor} == @concept_id"]
            bind_vars: dict[str, Any] = {
                "@edges": EDGES_COLLECTION,
                "@pages": PAGES_COLLECTION,
                "concept_id": concept_id,
            }
            if rel is not None:
                filters.append("e.rel == @rel")
                bind_vars["rel"] = rel
            filter_clause = " AND ".join(filters)
            aql = (
                "FOR e IN @@edges "
                f"FILTER {filter_clause} "
                f"LET p = DOCUMENT(@@pages, e.{other}) "
                "RETURN {concept_id: e." + other + ", rel: e.rel,"
                " title: p.title, category: p.category, summary: p.summary,"
                " token_count: p.token_count}"
            )
            rows = await self._query(aql, bind_vars)
            for row in rows:
                row["direction"] = dir_label
                results.append(row)
        return results

    async def dump_pages(self) -> list[dict[str, Any]]:
        """Return every page row WITH bodies (bulk export path)."""
        await self._ensure_init()
        aql = (
            "FOR doc IN @@collection SORT doc.concept_id "
            "RETURN {concept_id: doc.concept_id, node_id: doc.node_id,"
            " title: doc.title, category: doc.category, summary: doc.summary,"
            " body: doc.body, source_id: doc.source_id,"
            " token_count: doc.token_count, created_at: doc.created_at,"
            " updated_at: doc.updated_at}"
        )
        return await self._query(aql, {"@collection": PAGES_COLLECTION})

    async def dump_edges(self) -> list[dict[str, Any]]:
        """Return every edge row (bulk export path)."""
        await self._ensure_init()
        aql = "FOR e IN @@collection SORT e.src, e.dst, e.rel" " RETURN {src: e.src, dst: e.dst, rel: e.rel}"
        return await self._query(aql, {"@collection": EDGES_COLLECTION})

    async def stats(self) -> dict[str, Any]:
        """Aggregate counters for the wiki.

        Returns:
            ``{"pages": N, "edges": M, "sources": S, "embeddings": E,
            "total_tokens": T, "categories": {...}}``
        """
        await self._ensure_init()
        out: dict[str, Any] = {}
        for key, collection in (
            ("pages", PAGES_COLLECTION),
            ("edges", EDGES_COLLECTION),
            ("sources", SOURCES_COLLECTION),
            ("embeddings", EMBEDDINGS_COLLECTION),
        ):
            rows = await self._query(
                "FOR doc IN @@collection COLLECT WITH COUNT INTO length" " RETURN length",
                {"@collection": collection},
            )
            out[key] = rows[0] if rows else 0

        rows = await self._query(
            "RETURN SUM(FOR doc IN @@collection RETURN doc.token_count)",
            {"@collection": PAGES_COLLECTION},
        )
        out["total_tokens"] = rows[0] if rows else 0

        cat_rows = await self._query(
            "FOR doc IN @@collection COLLECT category = doc.category"
            " WITH COUNT INTO n RETURN {category: category, n: n}",
            {"@collection": PAGES_COLLECTION},
        )
        out["categories"] = {row["category"]: row["n"] for row in cat_rows}
        return out

    # ------------------------------------------------------------------
    # Lint API
    # ------------------------------------------------------------------

    async def orphan_sources(self) -> list[str]:
        """Sources that produced no pages (zero matching rows in pages)."""
        await self._ensure_init()
        aql = (
            "FOR s IN @@sources "
            "LET has_pages = LENGTH(FOR p IN @@pages"
            " FILTER p.source_id == s.source_id LIMIT 1 RETURN 1) > 0 "
            "FILTER NOT has_pages "
            "RETURN s.source_id"
        )
        return await self._query(aql, {"@sources": SOURCES_COLLECTION, "@pages": PAGES_COLLECTION})

    async def broken_edges(self) -> list[dict[str, Any]]:
        """Edges whose destination is neither a page nor a source."""
        await self._ensure_init()
        aql = (
            "FOR e IN @@edges "
            "LET page_exists = LENGTH(FOR p IN @@pages"
            " FILTER p.concept_id == e.dst LIMIT 1 RETURN 1) > 0 "
            "LET source_exists = LENGTH(FOR s IN @@sources"
            " FILTER s.source_id == e.dst LIMIT 1 RETURN 1) > 0 "
            "FILTER NOT page_exists AND NOT source_exists "
            "RETURN {src: e.src, dst: e.dst, rel: e.rel}"
        )
        return await self._query(
            aql,
            {
                "@edges": EDGES_COLLECTION,
                "@pages": PAGES_COLLECTION,
                "@sources": SOURCES_COLLECTION,
            },
        )

    async def missing_bodies(self) -> list[str]:
        """Pages with an empty body (stub rows without content)."""
        await self._ensure_init()
        aql = "FOR doc IN @@collection FILTER doc.body == '' RETURN doc.concept_id"
        return await self._query(aql, {"@collection": PAGES_COLLECTION})
