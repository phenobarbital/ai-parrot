from typing import Dict, Any
from enum import Enum
from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """
    Data model for a single document returned from a vector search.
    """
    id: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    score: float


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
