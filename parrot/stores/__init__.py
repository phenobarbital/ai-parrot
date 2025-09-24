from .abstract import AbstractStore
from .postgres import PgVectorStore
from .kb import KnowledgeBaseStore

supported_stores = {
    'postgres': 'PgVectorStore',
    'kb': 'KnowledgeBaseStore',
}
