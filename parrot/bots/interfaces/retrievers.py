from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStoreRetriever


class EmptyRetriever(BaseRetriever):
    """Return a Retriever with No results.
    """
    async def aget_relevant_documents(self, query: str):
        return []

    def _get_relevant_documents(self, query: str):
        return []
