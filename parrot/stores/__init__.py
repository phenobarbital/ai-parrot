from .abstract import AbstractStore
from .empty import EmptyStore

supported_stores = {
    'chroma': 'ChromaStore',
    'duck': 'DuckDBStore',
    'milvus': 'MilvusStore',
    'qdrant': 'QdrantStore',
    'postgres': 'PgvectorStore',
    'faiss': 'FaissStore',
}
