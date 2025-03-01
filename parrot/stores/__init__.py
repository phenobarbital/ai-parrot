from .abstract import AbstractStore

supported_stores = {
    'chroma': 'ChromaStore',
    'duck': 'DuckDBStore',
    'milvus': 'MilvusStore',
    'qdrant': 'QdrantStore',
    'postgres': 'PgvectorStore',
    'faiss': 'FaissStore',
}
