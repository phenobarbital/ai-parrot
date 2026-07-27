"""Search origin adapters for ``MultiStoreSearchToolkit`` (FEAT-379).

Exports the :class:`SearchOrigin` adapter contract and built-in adapters
as they land (vector store first; PageIndex/GraphIndex/wiki follow in
subsequent tasks).
"""
from .base import SearchOrigin
from .vector import VectorStoreOrigin

__all__ = (
    "SearchOrigin",
    "VectorStoreOrigin",
)
