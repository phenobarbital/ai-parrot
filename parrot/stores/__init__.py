from .abstract import AbstractStore

supported_stores = {
    'chroma': 'ChromaStore',
    'duck': 'DuckDBStore',
    'milvus': 'MilvusStore',
    'qdrant': 'QdrantStore',
    'pgvector': 'PgvectorStore',
    'faiss': 'FaissStore',
}
