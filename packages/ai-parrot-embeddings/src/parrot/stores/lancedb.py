"""LanceDB backend: lifecycle, collection setup and compatibility normalization.

Query methods are declared here but implemented by TASK-3064 (vector) and
TASK-3065 (FTS/hybrid). The SDK is imported lazily inside methods so this module
stays importable without ``ai-parrot-embeddings[lancedb]``.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta
from typing import Any, Callable, List, Union

from parrot.stores import AbstractStore  # verified: packages/ai-parrot-embeddings/tests/test_namespace_imports.py:151
from parrot.stores.lancedb_concurrency import MutationCoordinator  # new in TASK-3061
from parrot.stores.lancedb_models import (  # new in TASK-3059
    CollectionManifest,
    LanceDBConfig,
    build_arrow_schema,
    embedding_fingerprint,
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

_LEGACY_COLUMN_DEFAULTS = {
    "embedding_column": "embedding",
    "document_column": "document",
    "metadata_column": "cmetadata",
    "id_column": "id",
}


class LanceDBStore(AbstractStore):
    """Embedded vector, full-text and hybrid store over a local directory."""

    def __init__(self, embedding_model: Union[dict, str] = None, embedding: Union[dict, Callable] = None, **kwargs: Any) -> None:
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

        import lancedb  # lazy: keep this module importable without the extra

        kwargs: dict[str, Any] = {}
        if self._config.read_consistency_interval_seconds:
            kwargs["read_consistency_interval"] = timedelta(
                seconds=self._config.read_consistency_interval_seconds
            )
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
                "LanceDBStore has no open default collection; call connection() and "
                "create_collection() first"
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

    async def similarity_search(self, query: str, collection: Union[str, None] = None, limit: int = 2, **kwargs: Any) -> list:
        """Implemented by TASK-3064."""
        raise NotImplementedError("TASK-3064 owns vector search")

    async def from_documents(self, documents: List[Any], collection: Union[str, None] = None, **kwargs: Any) -> Callable:
        """Implemented by TASK-3063."""
        raise NotImplementedError("TASK-3063 owns ingestion")

    async def add_documents(self, documents: List[Any], collection: Union[str, None] = None, **kwargs: Any) -> None:
        """Implemented by TASK-3063."""
        raise NotImplementedError("TASK-3063 owns ingestion")

    async def delete_documents(self, documents: Any = None, pk: str = "source_type", values: Any = None, table: str = None, schema: str = None, collection: str = None, **kwargs: Any) -> int:
        """Implemented by TASK-3063."""
        raise NotImplementedError("TASK-3063 owns deletion")

    async def delete_documents_by_filter(self, search_filter: dict, table: str = None, schema: str = None, collection: str = None, **kwargs: Any) -> int:
        """Implemented by TASK-3063."""
        raise NotImplementedError("TASK-3063 owns deletion")

    async def fulltext_search(self, query: str, collection: Union[str, None] = None, limit: int = 10, **kwargs: Any) -> list:
        """Implemented by TASK-3065."""
        raise NotImplementedError("TASK-3065 owns FTS")

    async def hybrid_search(self, query: str, collection: Union[str, None] = None, limit: int = 10, **kwargs: Any) -> list:
        """Implemented by TASK-3065."""
        raise NotImplementedError("TASK-3065 owns hybrid search")

    async def mmr_search(self, **kwargs: Any) -> list:
        """Always raises: v1 supports exact similarity search only."""
        raise NotImplementedError(
            "LanceDBStore does not support MMR; v1 provides exact cosine search only."
        )
