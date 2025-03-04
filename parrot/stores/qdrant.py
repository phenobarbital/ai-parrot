from collections.abc import Callable
from typing import Union, Optional
from qdrant_client import QdrantClient, models
from langchain.docstore.document import Document
from langchain.memory import VectorStoreRetrieverMemory
from langchain_qdrant import Qdrant
from .abstract import AbstractStore
from ..conf import (
    QDRANT_PROTOCOL,
    QDRANT_HOST,
    QDRANT_PORT,
    QDRANT_USE_HTTPS,
    QDRANT_CONN_TYPE,
    QDRANT_URL
)


class QdrantStore(AbstractStore):
    """Qdrant DB Store Class.

    Using Qdrant as a Document Vector Store.

    """

    def __init__(
        self,
        embedding_model: Union[dict, str] = None,
        embedding: Union[dict, Callable] = None,
        **kwargs
    ):
        super().__init__(
            embedding_model=embedding_model,
            embedding=embedding,
            **kwargs
        )
        self.client: Optional[QdrantClient] = None
        self.host: str = kwargs.pop('host', QDRANT_HOST)
        self.port: int = kwargs.pop('port', QDRANT_PORT)
        self.use_https: bool = kwargs.pop('use_https', QDRANT_USE_HTTPS)
        self.protocol: str = kwargs.pop('protocol', QDRANT_PROTOCOL)
        self.conn_type: str = kwargs.pop('conn_type', QDRANT_CONN_TYPE)
        self.url: str = kwargs.pop('url', QDRANT_URL)
        self._host: str = f"{self.protocol}://{self.host}:{self.port}"

    async def connection(self):
        """Initialize Qdrant vector store.

        Connects to a Qdrant instance, if connection fails, raise error.
        """
        try:
            self._connection = QdrantClient(
                host=self.host,
                port=self.port,
            )
            collections = self._connection.get_collections().collections
            collection_names = [collection.name for collection in collections]
            if self.collection_name not in collection_names:
                print(
                    f"Collection '{self.collection_name}' not found, creating new one."
                )
                self._connection.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=len(self._embed_.embedding.embed_query("test")), distance=models.Distance.EUCLID
                    )
                )
            self.client = Qdrant(
                client=self._connection,
                collection_name=self.collection_name,
                embedding_function=self._embed_.embedding
            )
        except Exception as e:
            print(f"Error connecting to Qdrant: {e}")
            raise
        self._connected = True
        return self._connection

    async def disconnect(self) -> None:
        """Disconnects from Qdrant instance."""
        self.client = None # No explicit disconnect needed for QdrantClient in this context.
        self._connection = None
        self._connected = False

    def get_vector(
        self,
        embedding: Optional[Callable] = None,
    ) -> Qdrant:
        """Returns Qdrant VectorStore instance."""
        if embedding is not None:
            _embed_ = embedding
        else:
            _embed_ = self.create_embedding(
                embedding_model=self.embedding_model
            )
        if not self._connection:
            # Re-establish client if lost, but should not happen frequently in well-managed context.
            self._connection = QdrantClient(host=self.host, port=self.port)
        return Qdrant(
            client=self._connection,
            collection_name=self.collection_name,
            embedding_function=_embed_
        )

    async def from_documents(self, documents: list[Document], **kwargs):
        """Save Documents as Vectors in Qdrant."""
        vectordb = await Qdrant.afrom_documents(
            documents=documents,
            embedding=self._embed_.embedding,
            client=self.client,
            collection_name=self.collection_name,
            **kwargs
        )
        return vectordb

    async def add_documents(
        self,
        documents: list[Document],
        embedding: Optional[Callable] = None,
    ) -> bool:
        """Add Documents to Qdrant."""
        async with self:
            vector_db = self.get_vector(embedding=embedding)
            await vector_db.aadd_documents(documents=documents)
        return True

    async def update_documents(
        self,
        documents: list[Document],
        embedding: Optional[Callable] = None,
    ) -> bool:
        """Update Documents in Qdrant."""
        async with self:
            vector_db = self.get_vector(embedding=embedding)
            if all('id' in doc for doc in documents):
                ids = [doc.pop('id') for doc in documents]
                vector_db.delete(ids=ids)  # Remove old entries
                await vector_db.aadd_documents(documents=documents)  # Add new versions
                return True
            return False

    async def similarity_search(
        self,
        query: str,
        embedding: Optional[Callable] = None,
        limit: int = 2,
    ) -> list:
        """Performs similarity search in Qdrant."""
        async with self:
            vector_db = self.get_vector(embedding=embedding)
            return await vector_db.asimilarity_search(query, k=limit) # Use asimilarity_search for async

    def memory_retriever(
        self,
        documents: Optional[list] = None,
        num_results: int = 5
    ) -> VectorStoreRetrieverMemory:
        """Retrieves stored memory-based documents."""
        if not documents:
            documents = []
        vectordb = Qdrant.from_documents(
            documents=documents,
            embedding=self._embed_.embedding,
            client=self.client,
            collection_name=self.collection_name
        )
        retriever = Qdrant.as_retriever(
            vectordb,
            search_kwargs=dict(k=num_results)
        )
        return VectorStoreRetrieverMemory(retriever=retriever)
