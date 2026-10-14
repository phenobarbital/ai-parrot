from pkgutil import extend_path
from typing import Any

__path__ = extend_path(__path__, __name__)

# from .postgres import PgVectorStore
supported_stores = {
    "postgres": "PgVectorStore",
    "milvus": "MilvusStore",
    "kb": "KnowledgeBaseStore",
    "faiss_store": "FaissStore",
    "arango": "ArangoStore",
    "bigquery": "BigQueryStore",
    "lancedb": "LanceDBStore",
}

__all__ = ["AbstractStore", "supported_stores"]


def __getattr__(name: str) -> Any:
    """Resolve ``AbstractStore`` lazily to avoid its navconfig import.

    Args:
        name: Attribute requested on the package.

    Returns:
        The lazily resolved abstract store class.

    Raises:
        AttributeError: If ``name`` is not a public stores export.
    """
    if name == "AbstractStore":
        from .abstract import AbstractStore

        globals()[name] = AbstractStore
        return AbstractStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Expose lazy exports to ``dir()``."""
    return sorted(set(globals()) | set(__all__))
