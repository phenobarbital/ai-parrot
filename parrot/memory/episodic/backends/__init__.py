"""Episodic memory storage backends.

Available backends:
- PgVectorBackend: PostgreSQL + pgvector for production use.
- FAISSBackend: In-memory FAISS for local development.
"""
from .abstract import AbstractEpisodeBackend
from .pgvector import PgVectorBackend

__all__ = [
    "AbstractEpisodeBackend",
    "PgVectorBackend",
]

try:
    from .faiss import FAISSBackend

    __all__.append("FAISSBackend")
except ImportError:
    pass
