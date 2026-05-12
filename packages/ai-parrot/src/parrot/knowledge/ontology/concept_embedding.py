"""Concept embedding pipeline for the ontology knowledge layer (FEAT-159).

Provides ``ConceptEmbeddingPipeline``, an idempotent content-hash-based sync
that writes Concept embeddings into a shared PgVector ``concepts`` table scoped
by ``tenant_id`` metadata.  Only changed or new concepts are re-embedded on
each call, and removed concepts are deleted from the store.

The hash cache is persisted as JSON at::

    {ontology_dir}/.concept_hashes/{tenant_id}.json

Writes to the cache file are atomic (tmpfile + rename) to prevent corruption
from partial writes or process interruption.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConceptSyncResult:
    """Summary of a single ``ConceptEmbeddingPipeline.sync()`` run.

    Attributes:
        added: Number of new concepts embedded for the first time.
        updated: Number of existing concepts that were re-embedded (content changed).
        removed: Number of concepts deleted from the vector store.
        unchanged: Number of concepts whose content hash matched the cache
            (no embedding call made).
        duration_ms: Wall-clock time for the sync operation in milliseconds.
    """

    added: int
    updated: int
    removed: int
    unchanged: int
    duration_ms: int


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class ConceptEmbeddingPipeline:
    """Idempotent, hash-based embedding sync for ontology Concept instances.

    On each ``sync()`` call the pipeline:

    1. Computes a content hash (sha256) for every concept in the supplied list.
    2. Loads the on-disk hash cache for the tenant.
    3. Diffs new hashes against cached hashes to determine added / updated /
       removed / unchanged sets.
    4. Embeds *only* changed/new concepts via ``vector_store.add_documents()``.
    5. Deletes removed concepts via ``vector_store.delete_documents_by_filter()``.
    6. Atomically writes the updated hash cache to disk.

    The ``concepts`` table is shared across tenants; isolation is enforced by
    the ``tenant_id`` metadata field stored alongside each embedding row.

    Args:
        vector_store: PgVectorStore instance used for embedding storage.
        embedder: Callable or embedding client; passed to the vector store's
            ``add_documents`` for embedding.  If the vector store handles its
            own embedding, this can be the same object as ``vector_store``.
        ontology_dir: Base directory for ontology files.  The hash-cache
            subdirectory ``.concept_hashes/`` is created here.
        schema: PostgreSQL schema name for the concepts table.
        table: PostgreSQL table name for concept embeddings.
    """

    def __init__(
        self,
        vector_store: Any,
        embedder: Any,
        ontology_dir: Path | str,
        schema: str = "ontology",
        table: str = "concepts",
    ) -> None:
        self._vector_store = vector_store
        self._embedder = embedder
        self._ontology_dir = Path(ontology_dir)
        self._schema = schema
        self._table = table
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Content hashing
    # ------------------------------------------------------------------

    @staticmethod
    def _get_attr(concept: Any, attr: str, default: Any = None) -> Any:
        """Duck-typed attribute access — works with objects and dicts.

        Args:
            concept: A concept object or dict.
            attr: Attribute / key name.
            default: Value returned when the attribute is absent.

        Returns:
            The attribute value or *default*.
        """
        if isinstance(concept, dict):
            return concept.get(attr, default)
        return getattr(concept, attr, default)

    def _content_hash(self, concept: Any) -> str:
        """Compute a deterministic SHA-256 content hash for a concept.

        The hash is based on: ``label + sorted(synonyms) + description``.
        Synonym order does not affect the hash.

        Args:
            concept: Concept object or dict with ``label``, ``synonyms``, and
                ``description`` attributes/keys.

        Returns:
            Hex-encoded SHA-256 digest string.
        """
        label: str = self._get_attr(concept, "label", "") or ""
        synonyms: list[str] = list(self._get_attr(concept, "synonyms", []) or [])
        description: str = self._get_attr(concept, "description", "") or ""
        content = label + "".join(sorted(synonyms)) + description
        return hashlib.sha256(content.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Hash-cache persistence
    # ------------------------------------------------------------------

    def _cache_path(self, tenant_id: str) -> Path:
        """Return the hash-cache file path for a tenant.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            Path to the tenant's ``.json`` hash-cache file.
        """
        return self._ontology_dir / ".concept_hashes" / f"{tenant_id}.json"

    def _load_hash_cache(self, tenant_id: str) -> dict[str, str]:
        """Load the on-disk hash cache for a tenant.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            Mapping of ``concept_id`` → content-hash string.
            Returns an empty dict if the cache file does not exist.
        """
        cache_path = self._cache_path(tenant_id)
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                self.logger.warning(
                    "Failed to read concept hash cache for tenant '%s': %s; "
                    "treating as empty.",
                    tenant_id, exc,
                )
        return {}

    def _save_hash_cache(self, tenant_id: str, hashes: dict[str, str]) -> None:
        """Atomically write the hash cache for a tenant.

        Uses a tempfile-then-rename strategy to prevent partial writes.

        Args:
            tenant_id: Tenant identifier.
            hashes: Mapping of ``concept_id`` → content-hash string.
        """
        cache_dir = self._ontology_dir / ".concept_hashes"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = self._cache_path(tenant_id)

        fd, tmp_path = tempfile.mkstemp(dir=str(cache_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(hashes, f)
            Path(tmp_path).replace(cache_path)
        except Exception:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def sync(
        self,
        tenant_id: str,
        concepts: list[Any],
    ) -> ConceptSyncResult:
        """Synchronise concept embeddings for a tenant with the vector store.

        Idempotent: re-running with the same concepts produces no embedding
        calls and returns ``unchanged=len(concepts)``.

        Args:
            tenant_id: Tenant identifier used for metadata scoping and hash-
                cache namespacing.
            concepts: List of concept objects or dicts.  Each item must expose
                ``concept_id``, ``label``, ``synonyms``, and ``description``
                (either as attributes or dict keys).

        Returns:
            ``ConceptSyncResult`` with counts of added / updated / removed /
            unchanged concepts and the elapsed wall-clock duration in ms.
        """
        start_ms = int(time.monotonic() * 1000)

        added = updated = removed = unchanged = 0

        # --- Phase 1: compute current hashes --------------------------------
        current_hashes: dict[str, str] = {}
        for concept in concepts:
            cid = str(self._get_attr(concept, "concept_id", "") or "")
            if not cid:
                self.logger.debug("Concept without concept_id skipped: %r", concept)
                continue
            current_hashes[cid] = self._content_hash(concept)

        # --- Phase 2: load cached hashes ------------------------------------
        cached_hashes = self._load_hash_cache(tenant_id)

        # --- Phase 3: diff --------------------------------------------------
        to_add: list[Any] = []
        to_update: list[Any] = []
        cached_ids = set(cached_hashes)
        current_ids = set(current_hashes)

        for concept in concepts:
            cid = str(self._get_attr(concept, "concept_id", "") or "")
            if not cid:
                continue
            if cid not in cached_hashes:
                to_add.append(concept)
            elif current_hashes[cid] != cached_hashes[cid]:
                to_update.append(concept)
            else:
                unchanged += 1

        removed_ids = cached_ids - current_ids

        # --- Phase 4: embed added/updated -----------------------------------
        concepts_to_embed = to_add + to_update
        if concepts_to_embed:
            await self._embed_concepts(tenant_id, concepts_to_embed)
            added = len(to_add)
            updated = len(to_update)

        # --- Phase 5: delete removed ----------------------------------------
        for cid in removed_ids:
            try:
                await self._vector_store.delete_documents_by_filter(
                    filter_dict={"tenant_id": tenant_id, "concept_id": cid},
                    table=self._table,
                    schema=self._schema,
                )
                removed += 1
                self.logger.debug(
                    "Deleted concept '%s' for tenant '%s'", cid, tenant_id
                )
            except Exception as exc:
                self.logger.warning(
                    "Failed to delete concept '%s' for tenant '%s': %s",
                    cid, tenant_id, exc,
                )

        # --- Phase 6: update cache ------------------------------------------
        new_cache = {cid: current_hashes[cid] for cid in current_ids}
        self._save_hash_cache(tenant_id, new_cache)

        duration_ms = int(time.monotonic() * 1000) - start_ms
        result = ConceptSyncResult(
            added=added,
            updated=updated,
            removed=removed,
            unchanged=unchanged,
            duration_ms=duration_ms,
        )
        self.logger.info(
            "ConceptEmbeddingPipeline.sync tenant='%s': "
            "added=%d updated=%d removed=%d unchanged=%d duration_ms=%d",
            tenant_id, added, updated, removed, unchanged, duration_ms,
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _embed_concepts(
        self,
        tenant_id: str,
        concepts: list[Any],
    ) -> None:
        """Embed a list of concepts and write them to the vector store.

        Builds ``Document`` objects with per-concept metadata (``tenant_id``
        and ``concept_id``) and delegates to ``vector_store.add_documents()``.
        The ``metadata_filters`` parameter scopes the upsert delete-and-insert
        per concept so duplicate rows are not created on re-runs.

        Args:
            tenant_id: Tenant identifier.
            concepts: Non-empty list of concept objects or dicts to embed.
        """
        try:
            from parrot.stores.models import Document
        except ImportError:
            # Fallback: create a minimal Document-like object
            class Document:  # type: ignore[no-redef]
                def __init__(self, page_content: str, metadata: dict) -> None:
                    self.page_content = page_content
                    self.metadata = metadata

        documents = []
        for concept in concepts:
            cid = str(self._get_attr(concept, "concept_id", "") or "")
            label: str = self._get_attr(concept, "label", "") or ""
            synonyms: list[str] = list(self._get_attr(concept, "synonyms", []) or [])
            description: str = self._get_attr(concept, "description", "") or ""

            # Build a rich text representation for semantic search
            parts = [label]
            if synonyms:
                parts.append("synonyms: " + ", ".join(synonyms))
            if description:
                parts.append(description)
            page_content = " | ".join(parts)

            doc = Document(
                page_content=page_content,
                metadata={
                    "tenant_id": tenant_id,
                    "concept_id": cid,
                    "label": label,
                },
            )
            documents.append((cid, doc))

        for cid, doc in documents:
            await self._vector_store.add_documents(
                documents=[doc],
                table=self._table,
                schema=self._schema,
                metadata_filters={"tenant_id": tenant_id, "concept_id": cid},
            )
