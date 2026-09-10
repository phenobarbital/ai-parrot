"""LanceDB search origin: vector or native hybrid, plus an explicit FTS route.

Borrows an already-configured ``LanceDBStore``. Never opens or closes it —
the caller owns connection lifetime (spec §2). This module imports only
``parrot.models``/``.base`` — never ``lancedb`` or ``parrot.stores.lancedb``
— so importing it (and the whole origins package) never requires the
optional SDK extra.
"""

from __future__ import annotations

from typing import Any, Literal

from parrot.models import (
    OriginHit,
    SearchOriginKind,
)  # verified: packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:10

from .base import SearchOrigin  # verified: .../origins/vector.py:13


class LanceDBOrigin(SearchOrigin):
    """Federates LanceDB vector or native hybrid results into the toolkit.

    Args:
        store: An already-configured ``LanceDBStore`` (or any object
            exposing the same async ``similarity_search``/``fulltext_search``/
            ``hybrid_search`` surface). Borrowed — this origin never opens,
            closes, or disconnects it.
        name: Adapter name, defaults to ``"lancedb"``.
        description: LLM-readable explanation of this origin.
        mode: ``"vector"`` or ``"hybrid"`` — which method :meth:`search`
            dispatches to. :meth:`fts_search` always calls lexical search
            regardless of this setting.
        collection: Fixed collection/table scope for every call.
        metadata_filters: Fixed metadata filter scope for every call.
        include_parents: Fixed parent-visibility scope for every call.
        timeout: Optional per-adapter timeout override in seconds.
    """

    kind = SearchOriginKind.VECTOR

    def __init__(
        self,
        store: Any,
        *,
        name: str = "lancedb",
        description: str = "",
        mode: Literal["vector", "hybrid"] = "hybrid",
        collection: str | None = None,
        metadata_filters: dict[str, Any] | None = None,
        include_parents: bool = False,
        timeout: float | None = None,
    ) -> None:
        self.store = store
        self.name = name
        self.description = description or (
            f"LanceDB origin '{name}' — local {mode} search over an embedded " "vector/full-text collection."
        )
        self.mode = mode
        self.collection = collection
        self.metadata_filters = metadata_filters
        self.include_parents = include_parents
        self.timeout = timeout
        # Unlike VectorStoreOrigin (which computes this from a duck-typed
        # attribute check), LanceDBStore always provides native FTS.
        self.supports_fts = True

    async def search(self, query: str, k: int) -> list[OriginHit]:
        """Run the configured mode (``vector`` or ``hybrid``) with ``limit=k``.

        Errors and cancellation propagate unchanged — the toolkit isolates
        per-origin failures itself; this adapter never returns an empty
        success on backend failure (spec §8 whole-origin-failure answer).
        """
        if self.mode == "hybrid":
            results = await self.store.hybrid_search(
                query,
                collection=self.collection,
                limit=k,
                metadata_filters=self.metadata_filters,
                include_parents=self.include_parents,
            )
        else:
            results = await self.store.similarity_search(
                query,
                collection=self.collection,
                limit=k,
                metadata_filters=self.metadata_filters,
                include_parents=self.include_parents,
            )
        return self._to_hits(results)

    async def fts_search(self, query: str, k: int) -> list[OriginHit]:
        """Always route to lexical search, regardless of the configured mode."""
        results = await self.store.fulltext_search(
            query,
            collection=self.collection,
            limit=k,
            metadata_filters=self.metadata_filters,
            include_parents=self.include_parents,
        )
        return self._to_hits(results)

    def _to_hits(self, results: list[Any]) -> list[OriginHit]:
        """Normalize backend results into ``OriginHit`` with native score and rank.

        Preserves the native score value and the backend's own return
        order unchanged (native_rank is 1-based) — both ``SearchResult``
        (vector/FTS) and ``LanceDBHybridHit`` (hybrid) expose ``id``,
        ``content``, ``score`` and ``metadata`` with the same names, so one
        helper normalizes both without guessing a shared hybrid type.
        """
        return [
            OriginHit(
                id=getattr(result, "id", None),
                content=result.content,
                score=(float(result.score) if result.score is not None else None),
                metadata=dict(result.metadata or {}),
                origin=self.name,
                origin_kind=self.kind,
                native_rank=idx + 1,
            )
            for idx, result in enumerate(results)
        ]
