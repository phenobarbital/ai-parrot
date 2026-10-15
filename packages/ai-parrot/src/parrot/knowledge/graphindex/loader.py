"""Backward-compatible lazy export for the framework GraphIndex loader."""

from __future__ import annotations

from typing import Any

__all__ = ("GraphIndexLoader",)


def __getattr__(name: str) -> Any:
    """Resolve the moved loader only when legacy callers request it."""
    if name == "GraphIndexLoader":
        from parrot.loaders.graphindex import GraphIndexLoader

        return GraphIndexLoader
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Expose the compatibility export to introspection tools."""
    return sorted((*globals(), *__all__))
