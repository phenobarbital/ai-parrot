from .abstract import AbstractStore
# from .postgres import PgVectorStore
supported_stores = {
    'postgres': 'PgVectorStore',
    'milvus': 'MilvusStore',
    'kb': 'KnowledgeBaseStore',
}
