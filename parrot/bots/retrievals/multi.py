from typing import List
from collections.abc import Callable
from langchain.schema import Document

class MultiVectorStoreRetriever:
    """
    This aggregator retriever queries multiple vector stores
    and merges the results into a single list.
    """

    def __init__(
        self,
        stores: List[Callable],
        metric_type: str = 'COSINE',
        chain_type: str = 'stuff',
        search_type: str = 'similarity',
        search_kwargs: dict = None,
    ):
        """
        stores: List of AbstractStore or anything that provides an as_retriever() method
        search_kwargs: dict to pass on to each store's retrieve method (like 'k' for top_k)
        """
        self.stores = stores
        self.search_kwargs = search_kwargs or {}
        self.chain_type = chain_type
        self.search_type = search_type
        self.metric_type = metric_type

    def get_relevant_documents(self, query: str) -> List[Document]:
        all_results = []
        for store in self.stores:
            retriever = store.as_retriever(**self.search_kwargs)
            docs = retriever.get_relevant_documents(query)
            all_results.extend(docs)
        return all_results

    async def aget_relevant_documents(self, query: str) -> List[Document]:
        # Async version
        all_results = []
        for store in self.stores:
            async with store as st:
                retriever = st.as_retriever(
                    search_type=self.search_type,
                    search_kwargs=self.search_kwargs,
                    metric_type=self.metric_type,
                    chain_type=self.chain_type,
                )
                docs = await retriever.aget_relevant_documents(query)
                all_results.extend(docs)
        return all_results
