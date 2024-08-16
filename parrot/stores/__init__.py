from typing import Any
from .abstract import AbstractStore
from ..exceptions import ConfigError  # pylint: disable=E0611
try:
    from .qdrant import QdrantStore
    QDRANT_ENABLED = True
except (ModuleNotFoundError, ImportError):
    QDRANT_ENABLED = False

try:
    from .milvus import MilvusStore
    MILVUS_ENABLED = True
except (ModuleNotFoundError, ImportError):
    MILVUS_ENABLED = False


def get_vectordb(vector_db: str, embeddings: Any, **kwargs) -> AbstractStore:
    if vector_db in ('QdrantStore', 'qdrant'):
        if QDRANT_ENABLED is True:
            ## TODO: support pluggable vector store
            return QdrantStore(  # pylint: disable=E0110
                embeddings=embeddings,
                **kwargs
            )
        else:
            raise ConfigError(
                (
                    "Qdrant is enabled but not installed, "
                    "Hint: Please install with pip install -e .[qdrant]"
                )
            )
    if vector_db in ('milvus', 'MilvusStore'):
        if MILVUS_ENABLED is True:
            return MilvusStore(
                embeddings=embeddings,
                **kwargs
            )
        else:
            raise ConfigError(
                (
                    "Milvus is enabled but not installed, "
                    "Hint: Please install with pip install -e .[milvus]"
                )
            )
    else:
        raise ValueError(
            f"Vector Database {vector_db} not supported"
        )
