from typing import Dict, Any, Optional, Union
from enum import Enum
from dataclasses import dataclass, field
from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """
    Data model for a single document returned from a vector search.
    """
    id: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    score: float
    ensemble_score: float = None
    search_source: str = None
    similarity_rank: Optional[int] = None
    mmr_rank: Optional[int] = None


class Document(BaseModel):
    """
    A simple document model for adding data to the vector store.
    This replaces langchain.docstore.document.Document.
    """
    page_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DistanceStrategy(str, Enum):
    """Enumerator of the Distance strategies for calculating distances
    between vectors."""

    EUCLIDEAN_DISTANCE = "EUCLIDEAN_DISTANCE"
    MAX_INNER_PRODUCT = "MAX_INNER_PRODUCT"
    DOT_PRODUCT = "DOT_PRODUCT"
    JACCARD = "JACCARD"
    COSINE = "COSINE"


@dataclass
class StoreConfig:
    """Vector Store configuration dataclass."""
    vector_store: str = 'postgres'  # postgres, faiss, arango, etc.
    table: Optional[str] = None
    schema: str = 'public'
    embedding_model: Union[str, dict] = field(
        default_factory=lambda: {
            "model": "sentence-transformers/all-mpnet-base-v2",
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
