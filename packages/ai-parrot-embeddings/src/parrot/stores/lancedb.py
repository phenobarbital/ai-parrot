"""LanceDB backend: lifecycle, collection setup and compatibility normalization.

Query methods are declared here but implemented by TASK-3064 (vector) and
TASK-3065 (FTS/hybrid). The SDK is imported lazily inside methods so this module
stays importable without ``ai-parrot-embeddings[lancedb]``.
"""

from __future__ import annotations

import asyncio
import copy as _copy
import json
import logging
import math
import uuid
from datetime import timedelta
from typing import Any, Callable, List, Union

from parrot.models.stores import (
    SearchResult,
)  # verified: packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:11
from parrot.stores import AbstractStore  # verified: packages/ai-parrot-embeddings/tests/test_namespace_imports.py:151
from parrot.stores.lancedb_concurrency import MutationCoordinator  # new in TASK-3061
from parrot.stores.lancedb_filters import (  # new in TASK-3060
    _quote_literal,  # noqa: F401 — reused single escaping choke point, not duplicated here
    combine,
    compile_metadata_filter,
    parent_exclusion_clause,
)
from parrot.stores.lancedb_models import (  # new in TASK-3059
    RESERVED_METADATA_KEY,
    STANDARD_BOOL_FIELDS,
    STANDARD_STRING_FIELDS,
    CollectionManifest,
    LanceDBConfig,
    LanceDBHybridHit,
    build_arrow_schema,
    embedding_fingerprint,
    namespaced_id,
    record_id_for,
)

# Constructor kwargs that select/route to this backend or configure the base
# class, but are NOT LanceDBConfig fields — consumed explicitly rather than
# rejected as unknown (spec §2 "Compatibility adapters").
_ROUTING_KWARGS = ("name", "vector_database", "vector_store")
_BASE_CONTEXTUAL_KWARGS = ("contextual_embedding", "contextual_template", "contextual_max_header_tokens")
_LEGACY_PREPARE_KWARGS = (
    "embedding_column",
    "document_column",
    "metadata_column",
    "id_column",
    "use_jsonb",
    "create_all_indexes",
    "drop_columns",
)

_ALLOWED_CONFIG_FIELDS = frozenset(LanceDBConfig.model_fields) | {"table"}

_MISSING_SDK_MESSAGE = (
    "The 'lancedb' package is not installed. Install it with the optional "
    "extra: pip install 'ai-parrot-embeddings[lancedb]'"
)


def _import_lancedb() -> Any:
    """Import the ``lancedb`` SDK, or raise an actionable error naming the extra.

    Added in TASK-3067 (dispatch/selection integration): spec §7 requires
    "selecting/opening LanceDB reports the exact install extra when
    missing" — a bare ``ModuleNotFoundError`` from the lazy ``import
    lancedb`` inside :meth:`LanceDBStore.connection` did not satisfy that.
    This is a narrow, additive wrapper only; it changes no other behavior
    in this file.
    """
    try:
        import lancedb
    except ModuleNotFoundError as exc:
        raise ImportError(_MISSING_SDK_MESSAGE) from exc
    return lancedb


_LEGACY_COLUMN_DEFAULTS = {
    "embedding_column": "embedding",
    "document_column": "document",
    "metadata_column": "cmetadata",
    "id_column": "id",
}


class LanceDBStore(AbstractStore):
    """Embedded vector, full-text and hybrid store over a local directory."""

    def __init__(
        self, embedding_model: Union[dict, str] = None, embedding: Union[dict, Callable] = None, **kwargs: Any
    ) -> None:
        self.logger = logging.getLogger(__name__)

        remaining = dict(kwargs)

        # Factory-routing fields select US; they are not backend settings.
        for key in _ROUTING_KWARGS:
            remaining.pop(key, None)

        # `schema=None`/"public" is a no-op namespace; anything else unsupported.
        schema = remaining.pop("schema", None)
        if schema not in (None, "public"):
            raise ValueError(f"LanceDBStore does not support schema={schema!r}; only None/'public' are accepted")

        # Accept a null dsn from existing factories; reject a non-null DSN in
        # favor of explicit `uri`.
        dsn = remaining.pop("dsn", None)
        if dsn is not None:
            raise ValueError("LanceDBStore does not accept a non-null dsn; configure uri instead")

        remaining.pop("use_database", None)  # base-class toggle, not a backend setting

        base_kwargs = {k: remaining.pop(k) for k in _BASE_CONTEXTUAL_KWARGS if k in remaining}

        unknown = set(remaining) - _ALLOWED_CONFIG_FIELDS
        if unknown:
            raise ValueError(f"Unknown LanceDBStore constructor kwargs: {sorted(unknown)}")

        # Initialize base state WITHOUT embedding_model/embedding so the base
        # constructor does not eagerly build a provider (abstract.py:155).
        super().__init__(**base_kwargs)

        self._config: LanceDBConfig = LanceDBConfig(**remaining)

        # Lazy provider inputs — resolved only in _ensure_provider().
        self._embedding_model_input = embedding_model
        self._embedding_callable_input = embedding
        self._embedding_provider: Any = None
        self._provider_lock = asyncio.Lock()

        self._manifest: CollectionManifest | None = None
        # Per-collection manifest cache — self._manifest above mirrors only
        # this store's OWN configured default collection (matching
        # get_vector()'s "default table" contract), but every query/mutation
        # method also accepts a `collection=` override. Without this cache,
        # namespaced_id() could resolve the WRONG collection_uuid for a
        # non-default collection touched by the same store instance —
        # exactly what AC3 ("local IDs cannot collide across different
        # collection UUIDs") exists to prevent. Code review finding.
        self._manifest_cache: dict[str, CollectionManifest] = {}
        self._coordinator: MutationCoordinator = MutationCoordinator.for_directory(
            self._config.uri, self._config.collection_name
        )
        self._connection_handle: Any = None
        self._default_table: Any = None

    # ------------------------------------------------------------------
    # Lazy embedding provider
    # ------------------------------------------------------------------

    def _resolve_embedding_identity(self) -> str:
        """Stable embedding identity WITHOUT constructing a model.

        Explicit `embedding_id` wins. Otherwise derived from the normalized
        model/provider configuration. Contextual settings are part of the
        identity fingerprint (spec §2).
        """
        if self._config.embedding_id:
            return self._config.embedding_id
        source = self._embedding_model_input
        if source is None and isinstance(self._embedding_callable_input, (str, dict)):
            source = self._embedding_callable_input
        if source is not None:
            normalized = self._normalize_embedding_config(source)
            return embedding_fingerprint(normalized)
        raise ValueError(
            "LanceDBStore requires an explicit embedding_id when constructed with an "
            "injected embedding callable and no embedding_model configuration"
        )

    async def _ensure_provider(self) -> Any:
        """Construct the embedding provider on first vector use, never for FTS."""
        if self._embedding_provider is not None:
            return self._embedding_provider
        async with self._provider_lock:
            if self._embedding_provider is not None:
                return self._embedding_provider

            callable_input = self._embedding_callable_input
            if callable_input is not None and not isinstance(callable_input, (str, dict)):
                # Caller-injected provider object: borrowed, never freed by us.
                self._embedding_provider = callable_input
                self._embed_ = callable_input
                return self._embedding_provider

            config_source = self._embedding_model_input
            if config_source is None and isinstance(callable_input, (str, dict)):
                config_source = callable_input
            if config_source is None:
                raise RuntimeError(
                    "LanceDBStore has no embedding provider configured; vector/hybrid "
                    "search require embedding_model or embedding at construction time "
                    "(full-text search does not need one)."
                )
            normalized = self._normalize_embedding_config(config_source)
            # Registry lookup / model construction can block (I/O, weight
            # loading) — move it off the event loop.
            provider = await asyncio.to_thread(self.create_embedding, embedding_model=normalized)
            self._embedding_provider = provider
            self._embed_ = provider  # keep base-class attribute coherent (still borrowed)
            return self._embedding_provider

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connection(self) -> tuple:
        """Open the directory and return ``(connection, default_table_or_none)``.

        Idempotent. Never creates or replaces a collection.
        """
        if self._connection_handle is not None:
            return self._connection_handle, self._default_table

        lancedb = _import_lancedb()  # lazy: keep this module importable without the extra

        kwargs: dict[str, Any] = {}
        if self._config.read_consistency_interval_seconds:
            kwargs["read_consistency_interval"] = timedelta(seconds=self._config.read_consistency_interval_seconds)
        conn = await lancedb.connect_async(self._config.uri, **kwargs)

        self._connection_handle = conn
        self._connection = conn  # base class get_connection()/engine()
        self._connected = True

        default_table = None
        try:
            existing = await conn.table_names()
            if self._config.collection_name in existing:
                default_table = await conn.open_table(self._config.collection_name)
        except Exception:  # noqa: BLE001 — connecting must not fail on a missing table
            default_table = None
        self._default_table = default_table

        return self._connection_handle, self._default_table

    def get_vector(self, metric_type: str = None, **kwargs: Any):
        """Return the already-open default table, or raise.

        Raises:
            RuntimeError: the store is not connected to an existing
                collection. This accessor performs no I/O.
        """
        if self._default_table is None:
            raise RuntimeError(
                "LanceDBStore has no open default collection; call connection() and " "create_collection() first"
            )
        return self._default_table

    def get_connection(self) -> Any:
        return self._connection_handle

    # ------------------------------------------------------------------
    # Collection creation
    # ------------------------------------------------------------------

    async def create_collection(self, collection: str) -> None:
        """Create the Arrow schema and the native FTS index when missing.

        Idempotent on a compatible existing collection (including finishing
        FTS index preparation on retry). A failed FTS setup leaves an
        explicit initialization error, never a successful searchable
        collection. Never overwrites an existing table.
        """
        from lancedb.index import FTS  # lazy: keep this module importable without the extra

        conn, _ = await self.connection()
        identity = self._resolve_embedding_identity()

        async def _do_create() -> None:
            existing_names = await conn.table_names()
            if collection in existing_names:
                table = await conn.open_table(collection)
                schema = await table.schema()
                manifest = self._manifest_from_schema(schema)
                manifest.check_compatible(self._config, identity)
            else:
                manifest = CollectionManifest(
                    collection_uuid=str(uuid.uuid4()),
                    dimension=self._config.dimension,
                    metric_type=self._config.metric_type,
                    embedding_fingerprint=identity,
                    metadata_fields=dict(self._config.metadata_fields),
                )
                arrow_schema = build_arrow_schema(self._config, manifest)
                table = await conn.create_table(collection, schema=arrow_schema)

            # Idempotent FTS preparation — a retry after a prior failure
            # completes index prep without replacing rows.
            indices = list(await table.list_indices())
            has_fts = any(idx.columns == ["document"] for idx in indices) if indices else False
            if not has_fts:
                await table.create_index("document", config=FTS())

            # Always cache per-collection (namespaced_id() correctness for
            # ANY collection this store touches); only mirror into the
            # store's own "default" attributes when this IS that default
            # collection — same guard as add_documents/delete_documents.
            self._manifest_cache[collection] = manifest
            if collection == self._config.collection_name:
                self._manifest = manifest
                self._default_table = table

        await self._coordinator.run_mutation(_do_create, description=f"create_collection:{collection}")

    @staticmethod
    def _manifest_from_schema(schema: Any) -> CollectionManifest:
        raw = schema.metadata.get(b"lancedb_manifest") if schema.metadata else None
        if raw is None:
            raise ValueError(
                "Existing LanceDB table has no persisted manifest metadata; it was not "
                "created by this backend and cannot be safely reopened"
            )
        return CollectionManifest.model_validate_json(raw)

    async def prepare_embedding_table(
        self,
        tablename: str,
        conn: Any = None,
        embedding_column: str = "embedding",
        document_column: str = "document",
        metadata_column: str = "cmetadata",
        dimension: int = None,
        id_column: str = "id",
        use_jsonb: bool = True,
        drop_columns: bool = False,
        create_all_indexes: bool = True,
        **kwargs: Any,
    ) -> None:
        """Legacy-compatible alias for :meth:`create_collection`.

        Accepts ``conn=None`` or this store's own connection; default column
        labels; ``use_jsonb=True`` as a compatibility-only flag (no JSONB
        database is created). Rejects ``drop_columns=True``, a foreign
        connection, custom column labels and non-empty ``additional_columns``.
        Native FTS preparation is mandatory even when ``create_all_indexes``
        is False — this backend never requests an ANN index.
        """
        if drop_columns:
            raise ValueError("LanceDBStore.prepare_embedding_table does not support drop_columns=True")
        if conn is not None and conn is not self._connection_handle:
            raise ValueError("LanceDBStore.prepare_embedding_table does not accept a foreign connection")

        labels = {
            "embedding_column": embedding_column,
            "document_column": document_column,
            "metadata_column": metadata_column,
            "id_column": id_column,
        }
        for key, value in labels.items():
            if value != _LEGACY_COLUMN_DEFAULTS[key]:
                raise ValueError(
                    f"LanceDBStore.prepare_embedding_table does not support a custom "
                    f"{key}={value!r}; only the default legacy label "
                    f"{_LEGACY_COLUMN_DEFAULTS[key]!r} is accepted"
                )

        additional_columns = kwargs.pop("additional_columns", None)
        if additional_columns:
            raise ValueError("LanceDBStore.prepare_embedding_table does not support additional_columns")
        if kwargs:
            raise ValueError(f"Unknown prepare_embedding_table kwargs: {sorted(kwargs)}")

        if dimension is not None and dimension != self._config.dimension:
            raise ValueError(
                f"prepare_embedding_table dimension={dimension} conflicts with configured "
                f"dimension={self._config.dimension}"
            )
        # use_jsonb/create_all_indexes are compatibility-only flags: no JSONB
        # database is created, and native FTS preparation always happens
        # regardless of create_all_indexes.
        del use_jsonb, create_all_indexes

        await self.create_collection(tablename)

    # ------------------------------------------------------------------
    # Shutdown / resource ownership
    # ------------------------------------------------------------------

    async def disconnect(self) -> None:
        """Idempotent shutdown; waits for this store's in-flight operations."""
        # Waiting on the coordinator's shared in-process lock ensures any
        # run_mutation()/exclusive() critical section this store started
        # finishes before we drop the connection handle.
        async with self._coordinator._local_lock:  # noqa: SLF001 — same-module coordination primitive
            pass
        await self._free_resources()
        self._connection_handle = None
        self._connection = None
        self._default_table = None
        self._connected = False

    async def _free_resources(self) -> None:
        """Release borrowed providers WITHOUT calling their ``free()``.

        Both registry-returned (shared across stores) and caller-injected
        embeddings are borrowed here — calling `.free()` on either would
        break another consumer of the same model (AC4). The base class's
        `_free_resources` at `abstract.py:222` calls `.free()`; this
        override intentionally does not.
        """
        self._embedding_provider = None
        self._embed_ = None

    # ------------------------------------------------------------------
    # Query methods — implemented by TASK-3064 (vector) / TASK-3065 (FTS/hybrid)
    # ------------------------------------------------------------------

    async def similarity_search(
        self,
        query: str,
        collection: Union[str, None] = None,
        limit: int = 2,
        similarity_threshold: float = 0.0,
        search_strategy: str = "auto",
        metadata_filters: Union[dict, None] = None,
        include_parents: bool = False,
        **kwargs: Any,
    ) -> list:
        """Exact cosine search. Scores are RAW DISTANCES: lower is better.

        Raises:
            ValueError: non-positive/boolean/non-integer limit, out-of-range
                threshold, or an unsupported ``search_strategy``.
            LookupError: the collection does not exist.
        """
        if search_strategy != "auto":
            raise ValueError(
                f"LanceDBStore.similarity_search only supports search_strategy='auto' "
                f"(exact search); got {search_strategy!r}"
            )
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError(f"limit must be a positive integer, got {limit!r}")

        score_threshold = kwargs.pop("score_threshold", None)
        ceiling = self._distance_ceiling(similarity_threshold, score_threshold)

        table_alias = kwargs.pop("table", None)
        collection_name = self._resolve_collection_selector(table_alias, collection)

        schema_kw = kwargs.pop("schema", None)
        if schema_kw not in (None, "public"):
            raise ValueError(f"LanceDBStore.similarity_search does not support schema={schema_kw!r}")

        for column_kwarg, default_label in (
            ("content_column", "document"),
            ("embedding_column", "embedding"),
            ("metadata_column", "cmetadata"),
            ("id_column", "id"),
        ):
            value = kwargs.pop(column_kwarg, default_label)
            if value != default_label:
                raise ValueError(
                    f"LanceDBStore.similarity_search does not support a custom "
                    f"{column_kwarg}={value!r}; only the default {default_label!r} is accepted"
                )
        if kwargs:
            raise ValueError(f"Unknown similarity_search kwargs: {sorted(kwargs)}")

        # Blank query returns [] after parameter validation above, WITHOUT
        # generating an embedding (spec §2 "Filters, Parent Visibility and Limits").
        if not query or not query.strip():
            return []

        conn, _ = await self.connection()
        existing_names = await conn.table_names()
        if collection_name not in existing_names:
            raise LookupError(f"LanceDB collection {collection_name!r} does not exist")

        table = await conn.open_table(collection_name)
        manifest = await self._ensure_manifest_loaded(table, collection_name)

        metadata_clause = compile_metadata_filter(metadata_filters, self._config)
        parent_clause = None if include_parents else parent_exclusion_clause()
        predicate = combine(metadata_clause, parent_clause)

        provider = await self._ensure_provider()
        query_vector = await provider.embed_query(query)

        query_builder = table.query().nearest_to(query_vector).distance_type("cosine")
        if predicate:
            query_builder = query_builder.where(predicate)
        rows = await query_builder.limit(limit).to_list()

        results: list[SearchResult] = []
        for row in rows:
            distance = float(row["_distance"])
            if ceiling is not None and distance > ceiling:
                continue
            record_id = row["record_id"]
            metadata = json.loads(row.get("metadata_json") or "{}")
            metadata[RESERVED_METADATA_KEY] = {
                "collection": collection_name,
                "record_id": record_id,
                "mode": "vector",
                "score_kind": "cosine_distance",
                "higher_is_better": False,
            }
            results.append(
                SearchResult(
                    id=namespaced_id(manifest.collection_uuid, record_id),
                    content=row["document"],
                    score=distance,
                    metadata=metadata,
                )
            )
        return results

    async def _ensure_manifest_loaded(self, table: Any, collection_name: str) -> CollectionManifest:
        """Read the persisted manifest for search-time provenance.

        Cached per ``collection_name`` (see ``self._manifest_cache``) so a
        store instance that queries more than one collection never resolves
        the wrong ``collection_uuid`` into ``namespaced_id()`` — a manifest
        cached for collection A must never be handed back for collection B.

        Unlike :meth:`create_collection`, this does NOT validate identity
        compatibility — a search-only caller (or FTS-only reopen) may have no
        embedding configuration at all, and reading the stored identity is
        exactly the "read without constructing" contract spec §2 requires.
        """
        cached = self._manifest_cache.get(collection_name)
        if cached is not None:
            return cached
        schema = await table.schema()
        manifest = self._manifest_from_schema(schema)
        self._manifest_cache[collection_name] = manifest
        if collection_name == self._config.collection_name:
            self._manifest = manifest
        return manifest

    def _distance_ceiling(self, similarity_threshold: float, score_threshold: float | None) -> float | None:
        """Translate similarity thresholds into a maximum cosine distance.

        ``similarity_threshold == 0.0`` disables thresholding (base
        compatibility default). A tool-supplied ``score_threshold`` is
        evaluated independently — including an explicit ``0.0``, which is
        NOT the disable sentinel here (only ``similarity_threshold``'s
        default has that meaning). When both are enabled, the STRICTER one
        (smaller resulting distance ceiling) wins.
        """
        ceilings: list[float] = []
        if similarity_threshold != 0.0:
            if not (0.0 < similarity_threshold <= 1.0):
                raise ValueError(f"similarity_threshold must be in (0, 1], got {similarity_threshold!r}")
            ceilings.append(1.0 - similarity_threshold)
        if score_threshold is not None:
            if not (0.0 <= score_threshold <= 1.0):
                raise ValueError(f"score_threshold must be in [0, 1], got {score_threshold!r}")
            ceilings.append(1.0 - score_threshold)
        if not ceilings:
            return None
        return min(ceilings)

    async def from_documents(
        self, documents: List[Any], collection: Union[str, None] = None, **kwargs: Any
    ) -> Callable:
        """Prepare the collection, add the documents and return this store."""
        collection_name = collection or self._config.collection_name
        await self.create_collection(collection_name)
        if documents:
            await self.add_documents(documents, collection=collection_name, **kwargs)
        return self

    async def add_documents(self, documents: List[Any], collection: Union[str, None] = None, **kwargs: Any) -> None:
        """Upsert documents into an existing prepared collection.

        Raises:
            LookupError: the collection does not exist.
            ValueError: conflicting or duplicate IDs, invalid metadata, or an
                invalid embedding vector, for ANY document in the input —
                validated for the whole input before any batch is written.
        """
        collection_name = collection or self._config.collection_name
        conn, _ = await self.connection()
        existing_names = await conn.table_names()
        if collection_name not in existing_names:
            raise LookupError(
                f"LanceDB collection {collection_name!r} does not exist; call "
                f"create_collection()/from_documents() first"
            )
        if not documents:
            return

        # 1) Resolve IDs, 2) validate IDs/metadata for the FULL input, BEFORE
        # any write and BEFORE contextual augmentation (spec §2 "Data Models").
        explicit_ids = kwargs.get("ids")
        record_ids = self._resolve_ids(documents, explicit_ids)
        for document in documents:
            self._validate_metadata(document.metadata or {})

        # 3) Deep-copy documents; augment COPIES only, never caller objects.
        copies = [_copy.deepcopy(document) for document in documents]
        texts_to_embed = self._apply_contextual_augmentation(copies, _log=False)

        provider = await self._ensure_provider()

        batch_size = self._config.batch_size
        total = len(documents)
        total_batches = (total + batch_size - 1) // batch_size
        completed_batches = 0

        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            batch_texts = texts_to_embed[start:end]
            batch_original_text = [documents[i].page_content for i in range(start, end)]
            batch_metadata = [copies[i].metadata or {} for i in range(start, end)]
            batch_ids = record_ids[start:end]

            try:
                # 4) Embed the batch, validate every vector, then merge-insert
                # under process-safe coordination with a fresh table handle.
                # Embedding failures count as this batch's failure too — the
                # reported "completed batch count" must reflect committed
                # writes regardless of which step inside the batch failed.
                vectors = await provider.embed_documents(batch_texts)
                for vector in vectors:
                    self._validate_vector(vector)

                rows = [
                    self._row_for(batch_ids[j], batch_original_text[j], batch_metadata[j], vectors[j])
                    for j in range(len(vectors))
                ]

                async def _do_upsert(rows: list[dict[str, Any]] = rows) -> None:
                    table = await conn.open_table(collection_name)
                    merge = table.merge_insert("record_id")
                    merge = merge.when_matched_update_all().when_not_matched_insert_all()
                    await merge.execute(rows)
                    # Refresh the cached default-table handle to the one that
                    # just committed, so synchronous get_vector()/search
                    # callers never see a pre-write snapshot (the same
                    # staleness the TASK-3057 gate found for cross-handle
                    # reads).
                    if collection_name == self._config.collection_name:
                        self._default_table = table

                await self._coordinator.run_mutation(_do_upsert, description=f"add_documents:{collection_name}")
            except Exception as exc:  # noqa: BLE001 — re-raised with batch accounting, never logging content
                raise RuntimeError(
                    f"add_documents failed after {completed_batches} of {total_batches} "
                    f"batches committed to {collection_name!r}. Completed batches are "
                    f"durable (no all-batch rollback); retrying with the same stable IDs "
                    f"is idempotent."
                ) from exc
            completed_batches += 1

    def _resolve_ids(self, documents: List[Any], explicit_ids: Any) -> list[str]:
        if explicit_ids is not None and len(explicit_ids) != len(documents):
            raise ValueError("ids must align 1:1 with documents")
        resolved: list[str] = []
        seen: set[str] = set()
        for index, document in enumerate(documents):
            explicit_id = explicit_ids[index] if explicit_ids is not None else None
            metadata = document.metadata or {}
            meta_id = metadata.get("id")
            if not (isinstance(meta_id, str) and meta_id):
                meta_id = None
            if explicit_id is not None and meta_id is not None and explicit_id != meta_id:
                raise ValueError(
                    f"Conflicting IDs for document {index}: explicit id {explicit_id!r} vs "
                    f"metadata['id'] {meta_id!r}"
                )
            record_id = explicit_id or meta_id
            if record_id is None:
                # Fallback ID is computed from the ORIGINAL text/metadata,
                # BEFORE any contextual augmentation.
                record_id = record_id_for(document.page_content, metadata)
            if record_id in seen:
                raise ValueError(f"Duplicate id {record_id!r} in one ingestion call")
            seen.add(record_id)
            resolved.append(record_id)
        return resolved

    @staticmethod
    def _validate_metadata(metadata: dict[str, Any]) -> None:
        if RESERVED_METADATA_KEY in metadata:
            raise ValueError(f"metadata may not use the reserved key {RESERVED_METADATA_KEY!r}")
        LanceDBStore._check_json_safe(metadata)

    @staticmethod
    def _check_json_safe(value: Any) -> None:
        if isinstance(value, bool) or value is None or isinstance(value, str):
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("metadata contains a non-finite number")
            return
        if isinstance(value, int):
            return
        if isinstance(value, dict):
            for nested in value.values():
                LanceDBStore._check_json_safe(nested)
            return
        if isinstance(value, (list, tuple)):
            for nested in value:
                LanceDBStore._check_json_safe(nested)
            return
        raise ValueError(f"metadata contains a non-JSON value of type {type(value).__name__}")

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != self._config.dimension:
            raise ValueError(f"embedding dimension mismatch: expected {self._config.dimension}, got {len(vector)}")
        if not all(math.isfinite(v) for v in vector):
            raise ValueError("embedding contains a non-finite value")
        if all(v == 0 for v in vector):
            raise ValueError("embedding is a zero-norm vector")

    def _row_for(
        self, record_id: str, original_text: str, metadata: dict[str, Any], vector: list[float]
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "record_id": record_id,
            "document": original_text,
            "embedding": vector,
            "metadata_json": json.dumps(metadata, sort_keys=True, default=str),
        }
        for field in (*STANDARD_STRING_FIELDS, *STANDARD_BOOL_FIELDS, *self._config.metadata_fields):
            row[f"meta_{field}"] = metadata.get(field)
        return row

    def _resolve_collection_selector(self, table: str | None, collection: str | None) -> str:
        if table is not None and collection is not None and table != collection:
            raise ValueError(f"Conflicting table={table!r} vs collection={collection!r} selectors")
        return table or collection or self._config.collection_name

    def _record_id_in_clause(self, record_ids: list[str]) -> str:
        if not record_ids:
            return "(1 = 0)"
        literals = ", ".join(_quote_literal(record_id) for record_id in record_ids)
        return f"record_id IN ({literals})"

    async def delete_documents(
        self,
        documents: Any = None,
        pk: str = "source_type",
        values: Any = None,
        table: str = None,
        schema: str = None,
        collection: str = None,
        **kwargs: Any,
    ) -> int:
        """Delete by document identity or by ``pk`` + ``values``. Returns rows removed.

        Raises:
            ValueError: empty filter, missing selector, or conflicting selectors.
        """
        del schema  # schema is a no-op namespace; validated at construction time
        collection_name = self._resolve_collection_selector(table, collection)

        if documents is None and values is None:
            raise ValueError(
                "delete_documents requires either `documents` or `pk`+`values`; there is "
                "no implicit delete-all operation"
            )
        if documents is not None and values is not None:
            raise ValueError("delete_documents received both `documents` and `values`; conflicting selectors")

        if documents is not None:
            if not documents:
                raise ValueError("delete_documents `documents` selector must be non-empty")
            record_ids: list[str] = []
            for item in documents:
                if isinstance(item, str):
                    record_ids.append(item)
                    continue
                metadata = getattr(item, "metadata", None) or {}
                meta_id = metadata.get("id")
                explicit_id = meta_id if isinstance(meta_id, str) and meta_id else None
                record_ids.append(explicit_id or record_id_for(item.page_content, metadata))
            predicate = self._record_id_in_clause(record_ids)
        else:
            values_list = [values] if isinstance(values, str) else list(values or [])
            if not values_list:
                raise ValueError("delete_documents `values` selector must be non-empty")
            if pk == "id":
                predicate = self._record_id_in_clause(values_list)
            else:
                if pk not in self._config.metadata_fields and pk not in STANDARD_STRING_FIELDS:
                    raise ValueError(f"delete_documents pk={pk!r} must be 'id' or a declared metadata field")
                predicate = compile_metadata_filter({pk: values_list}, self._config)

        async def _do_delete() -> int:
            conn, _ = await self.connection()
            table_handle = await conn.open_table(collection_name)
            result = await table_handle.delete(predicate)
            if collection_name == self._config.collection_name:
                self._default_table = table_handle
            return result.num_deleted_rows

        return await self._coordinator.run_mutation(_do_delete, description=f"delete_documents:{collection_name}")

    async def delete_documents_by_filter(
        self, search_filter: dict, table: str = None, schema: str = None, collection: str = None, **kwargs: Any
    ) -> int:
        """Delete by compiled metadata predicate (no parent-exclusion clause). Returns rows removed."""
        del schema
        collection_name = self._resolve_collection_selector(table, collection)
        if not search_filter:
            raise ValueError(
                "delete_documents_by_filter requires a non-empty search_filter; there is "
                "no implicit delete-all operation"
            )
        # Deletion reuses the metadata compiler WITHOUT the search-only
        # parent-exclusion clause: a caller deleting source='x' expects
        # matching parents to go too (spec §2 "Filters").
        predicate = compile_metadata_filter(search_filter, self._config)
        if predicate is None:
            raise ValueError(
                "delete_documents_by_filter requires a non-empty search_filter; there is "
                "no implicit delete-all operation"
            )

        async def _do_delete() -> int:
            conn, _ = await self.connection()
            table_handle = await conn.open_table(collection_name)
            result = await table_handle.delete(predicate)
            if collection_name == self._config.collection_name:
                self._default_table = table_handle
            return result.num_deleted_rows

        return await self._coordinator.run_mutation(
            _do_delete, description=f"delete_documents_by_filter:{collection_name}"
        )

    async def fulltext_search(
        self,
        query: str,
        collection: Union[str, None] = None,
        limit: int = 10,
        metadata_filters: dict[str, Any] | None = None,
        include_parents: bool = False,
        **kwargs: Any,
    ) -> list:
        """Native BM25 lexical search. Constructs no embedding model.

        Scores are native BM25 (higher is better). The inherited
        ``SearchResult.distance`` alias is therefore numerically BM25 and is
        NOT a distance — this limitation is documented, not a bug.
        """
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError(f"limit must be a positive integer, got {limit!r}")
        table_alias = kwargs.pop("table", None)
        collection_name = self._resolve_collection_selector(table_alias, collection)
        schema_kw = kwargs.pop("schema", None)
        if schema_kw not in (None, "public"):
            raise ValueError(f"LanceDBStore.fulltext_search does not support schema={schema_kw!r}")
        if kwargs:
            raise ValueError(f"Unknown fulltext_search kwargs: {sorted(kwargs)}")

        if not query or not query.strip():
            return []

        conn, _ = await self.connection()
        existing_names = await conn.table_names()
        if collection_name not in existing_names:
            raise LookupError(f"LanceDB collection {collection_name!r} does not exist")

        # NOTE (AC6): self._ensure_provider() is NEVER called anywhere in
        # this method — FTS must neither construct nor invoke an embedding
        # model, including on a reopen with no usable provider configured.
        table = await conn.open_table(collection_name)
        manifest = await self._ensure_manifest_loaded(table, collection_name)

        metadata_clause = compile_metadata_filter(metadata_filters, self._config)
        parent_clause = None if include_parents else parent_exclusion_clause()
        predicate = combine(metadata_clause, parent_clause)

        query_builder = table.query().nearest_to_text(query)
        if predicate:
            query_builder = query_builder.where(predicate)
        rows = await query_builder.limit(limit).to_list()

        results: list[SearchResult] = []
        for row in rows:
            record_id = row["record_id"]
            metadata = json.loads(row.get("metadata_json") or "{}")
            metadata[RESERVED_METADATA_KEY] = {
                "collection": collection_name,
                "record_id": record_id,
                "mode": "fts",
                "score_kind": "bm25",
                "higher_is_better": True,
            }
            results.append(
                SearchResult(
                    id=namespaced_id(manifest.collection_uuid, record_id),
                    content=row["document"],
                    score=float(row["_score"]),
                    metadata=metadata,
                )
            )
        return results

    async def hybrid_search(
        self,
        query: str,
        collection: Union[str, None] = None,
        limit: int = 10,
        metadata_filters: dict[str, Any] | None = None,
        include_parents: bool = False,
        **kwargs: Any,
    ) -> list:
        """Native vector/FTS fusion. Returns ``LanceDBHybridHit``; no distance alias.

        Raises:
            Exception: whatever the SDK (or the provider) raises when either
                leg fails. There is no fallback to a single leg — a failed
                hybrid fails the whole call (spec §8 whole-origin-failure
                answer).
        """
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError(f"limit must be a positive integer, got {limit!r}")
        table_alias = kwargs.pop("table", None)
        collection_name = self._resolve_collection_selector(table_alias, collection)
        schema_kw = kwargs.pop("schema", None)
        if schema_kw not in (None, "public"):
            raise ValueError(f"LanceDBStore.hybrid_search does not support schema={schema_kw!r}")
        if kwargs:
            raise ValueError(f"Unknown hybrid_search kwargs: {sorted(kwargs)}")

        if not query or not query.strip():
            return []

        conn, _ = await self.connection()
        existing_names = await conn.table_names()
        if collection_name not in existing_names:
            raise LookupError(f"LanceDB collection {collection_name!r} does not exist")

        table = await conn.open_table(collection_name)
        manifest = await self._ensure_manifest_loaded(table, collection_name)

        # ONE compiled predicate, reused for both legs via a single chained
        # query builder — spec §2 requires one conjunctive prefilter across
        # vector, FTS and both hybrid components (verified against the real
        # SDK: a single trailing .where() on a nearest_to()+nearest_to_text()
        # chain filters both legs, not just one).
        metadata_clause = compile_metadata_filter(metadata_filters, self._config)
        parent_clause = None if include_parents else parent_exclusion_clause()
        predicate = combine(metadata_clause, parent_clause)

        provider = await self._ensure_provider()
        query_vector = await provider.embed_query(query)

        query_builder = table.query().nearest_to(query_vector).distance_type("cosine").nearest_to_text(query)
        if predicate:
            query_builder = query_builder.where(predicate)
        rows = await query_builder.limit(limit).to_list()

        # Retain the SDK's native RRF order — do not re-sort.
        hits: list[LanceDBHybridHit] = []
        for rank, row in enumerate(rows, start=1):
            record_id = row["record_id"]
            metadata = json.loads(row.get("metadata_json") or "{}")
            metadata[RESERVED_METADATA_KEY] = {
                "collection": collection_name,
                "record_id": record_id,
                "mode": "hybrid",
                "score_kind": "rrf",
                "higher_is_better": True,
                "native_rank": rank,
            }
            hits.append(
                LanceDBHybridHit(
                    id=namespaced_id(manifest.collection_uuid, record_id),
                    content=row["document"],
                    metadata=metadata,
                    score=float(row["_relevance_score"]),
                )
            )
        return hits

    async def mmr_search(self, **kwargs: Any) -> list:
        """Always raises: v1 supports exact similarity search only."""
        raise NotImplementedError("LanceDBStore does not support MMR; v1 provides exact cosine search only.")
