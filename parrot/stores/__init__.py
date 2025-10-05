from .abstract import AbstractStore
from .postgres import PgVectorStore

supported_stores = {
    'postgres': 'PgVectorStore',
    'kb': 'KnowledgeBaseStore',
}
