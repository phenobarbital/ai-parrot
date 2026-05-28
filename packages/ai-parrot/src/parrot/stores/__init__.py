from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

from .abstract import AbstractStore
# from .postgres import PgVectorStore
supported_stores = {
    'postgres': 'PgVectorStore',
    'milvus': 'MilvusStore',
    'kb': 'KnowledgeBaseStore',
    'faiss_store': 'FaissStore',
    'arango': 'ArangoStore',
    'bigquery': 'BigQueryStore',
}
