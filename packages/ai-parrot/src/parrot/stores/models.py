"""Store data models.

``SearchResult`` and ``StoreConfig`` moved to :mod:`parrot.models.stores`
(the dependency-free core models package) so that consumers can import the
data contracts without triggering ``parrot.stores.__init__`` (which pulls in
``AbstractStore`` and the heavy store/embedding backends). They are
re-exported here for backward compatibility — existing
``from parrot.stores.models import SearchResult, StoreConfig`` keeps working.
"""

from typing import Dict, Any
from enum import Enum
from pydantic import BaseModel, Field

# Re-exported from the canonical, dependency-free home.
from ..models.stores import SearchResult, StoreConfig  # noqa: F401


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


__all__ = (
    "SearchResult",
    "Document",
    "DistanceStrategy",
    "StoreConfig",
)
