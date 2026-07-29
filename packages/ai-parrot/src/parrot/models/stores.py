"""Store-identifier and store data models.

Lightweight, dependency-free models for the vector/graph stores supported
by AI-Parrot. Lives in ``parrot.models`` (core) so that the store-routing
registry, bots and tools can reference store identifiers and the shared
data contracts (``StoreConfig``, ``SearchResult``) **without** importing
from ``parrot.stores`` — whose package ``__init__`` eagerly pulls in
``AbstractStore`` → ``parrot.embeddings`` → ``parrot.conf`` …  Importing
those models from here keeps the dependency graph acyclic and avoids the
heavy store backends (which now ship from ``ai-parrot-embeddings``).

``parrot.stores.models`` re-exports ``StoreConfig`` and ``SearchResult``
from this module for backward compatibility.
"""

from typing import Dict, Any, List, Optional, Union, Protocol, runtime_checkable
from enum import Enum
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, computed_field


class StoreType(Enum):
    """DB Store type — source of truth for store identifiers."""

    PGVECTOR = "pgvector"
    FAISS = "faiss"
    ARANGO = "arango"


class SearchOriginKind(Enum):
    """Kinds of multi-search origins (FEAT-379).

    Distinct from :class:`StoreType`, which stays DB-store-only.
    ``SearchOriginKind`` classifies the retrieval *plane* a
    ``SearchOrigin`` adapter wraps (vector-store, PageIndex, GraphIndex,
    or the ParrotWiki/LLM-Wiki store).
    """

    VECTOR = "vector"
    PAGEINDEX = "pageindex"
    GRAPHINDEX = "graphindex"
    WIKI = "wiki"


class SearchResult(BaseModel):
    """Data model for a single document returned from a vector search.

    ``score`` carries the raw value produced by the configured vector-store
    metric (e.g. L2 / cosine distance / negative inner product). For
    distance-based metrics (the common case) **lower means closer**. The
    same value is also serialised as ``distance`` via a computed alias so
    API consumers can use the unambiguous name without any input changes
    on the producer side.
    """
    id: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    score: float = Field(
        ...,
        description=(
            "Raw value from the configured metric. For L2 / cosine / "
            "negative-inner-product, lower = closer. Also exposed as "
            "``distance`` in serialised output."
        ),
    )
    ensemble_score: float = None
    search_source: str = None
    similarity_rank: Optional[int] = None
    mmr_rank: Optional[int] = None

    @computed_field  # type: ignore[misc]
    @property
    def distance(self) -> float:
        """Alias for :attr:`score` — same value, unambiguous name."""
        return self.score


class OriginHit(BaseModel):
    """One normalized result from any multi-search origin (FEAT-379).

    ``score`` is origin-native and is **not** comparable across origins
    (a vector-store distance, a wiki FTS rank, and a graph score live on
    different scales). Only :attr:`native_rank` — the hit's 1-based
    position within its own origin's ranking — is safe to compare within
    that origin.
    """

    id: Optional[str] = None
    content: str
    score: Optional[float] = Field(
        default=None,
        description=(
            "Origin-native score; NOT cross-origin comparable. See "
            "MultiSearchResponse.notes for the score-comparability caveat."
        ),
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)
    origin: str = Field(..., description="Adapter name, e.g. 'pgvector', 'wiki'.")
    origin_kind: SearchOriginKind
    native_rank: int = Field(
        ..., description="1-based position in the origin's own ranking."
    )


class OriginSection(BaseModel):
    """Grouped per-origin block of a multi-search response (FEAT-379)."""

    origin: str
    origin_kind: SearchOriginKind
    description: str = Field(
        ..., description="LLM-readable explanation of this origin."
    )
    status: str = Field(
        ..., description="One of 'ok' | 'error' | 'timeout' | 'skipped'."
    )
    note: Optional[str] = Field(
        default=None, description="Error/timeout/skip explanation, if any."
    )
    hits: List[OriginHit] = Field(
        default_factory=list,
        description="Native order preserved; may be empty.",
    )


class MultiSearchResponse(BaseModel):
    """``store_search`` / ``fts_search`` payload (FEAT-379).

    Carries BOTH the grouped-by-origin sections (native ranking, kept
    intact even with cross-origin duplicates) AND a merged,
    BM25-reranked, deduped top-k block.
    """

    query: str
    sections: List[OriginSection] = Field(default_factory=list)
    merged_top_k: List[OriginHit] = Field(
        default_factory=list,
        description="BM25-reranked + deduped across origins.",
    )
    notes: List[str] = Field(
        default_factory=list,
        description="e.g. 'score scales are origin-native'.",
    )


@runtime_checkable
class MultiSearch(Protocol):
    """Narrow protocol core code types against (FEAT-379).

    Defined in core so that ``StoreRouter`` (FAN_OUT) and ``AbstractBot``
    can depend on this protocol without importing ``parrot_tools``. Any
    object exposing an async ``search`` method with this signature
    satisfies the protocol — in particular, ``MultiStoreSearchToolkit``
    from ``ai-parrot-tools``.
    """

    async def search(self, query: str, k: Optional[int] = None, **kwargs) -> Any:
        ...


@dataclass
class StoreConfig:
    """Vector Store configuration dataclass."""
    vector_store: str = 'postgres'  # postgres, faiss, arango, etc.
    table: Optional[str] = None
    schema: str = 'public'
    embedding_model: Union[str, dict] = field(
        default_factory=lambda: {
            "model_name": "sentence-transformers/all-mpnet-base-v2",
            "model_type": "huggingface"
        }
    )
    dimension: int = 768
    dsn: Optional[str] = None
    distance_strategy: str = 'COSINE'
    metric_type: str = 'COSINE'
    index_type: str = 'IVF_FLAT'
    auto_create: bool = False  # Auto-create collection on configure
    extra: Dict[str, Any] = field(default_factory=dict)
