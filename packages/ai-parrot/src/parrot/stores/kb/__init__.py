import logging

from .abstract import AbstractKnowledgeBase
from .redis import RedisKnowledgeBase

# Suppress noisy DEBUG output from httpcore/httpx during KB operations
logging.getLogger("httpcore").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.INFO)

__all__ = (
    'AbstractKnowledgeBase',
    'RedisKnowledgeBase',
    'LocalKB',
)


def __getattr__(name: str):
    """Lazy-load LocalKB (requires ai-parrot-embeddings)."""
    if name == "LocalKB":
        from .local import LocalKB  # noqa: F811
        return LocalKB
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
