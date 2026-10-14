"""Compatibility path for GraphIndexEmbedder — the class lives in parrot.embeddings.graphindex (FEAT-540)."""

from typing import Any

__all__ = ["GraphIndexEmbedder"]


def __getattr__(name: str) -> Any:
    """Lazily resolve ``GraphIndexEmbedder`` so importing this module loads no faiss."""
    if name == "GraphIndexEmbedder":
        from parrot.embeddings.graphindex import GraphIndexEmbedder

        return GraphIndexEmbedder
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
