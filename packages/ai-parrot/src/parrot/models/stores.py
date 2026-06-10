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

from typing import Dict, Any, Optional, Union
from enum import Enum
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, computed_field


class StoreType(Enum):
    """DB Store type — source of truth for store identifiers."""

    PGVECTOR = "pgvector"
    FAISS = "faiss"
    ARANGO = "arango"


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
