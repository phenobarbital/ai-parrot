from collections.abc import Callable
from pathlib import PurePath
from typing import Optional, Union
from uuid import uuid4
import faiss
from langchain.docstore.document import Document
from langchain.memory import VectorStoreRetrieverMemory
from langchain_community.vectorstores import FAISS
from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_community.vectorstores.utils import DistanceStrategy
from .abstract import AbstractStore


class FaissStore(AbstractStore):
    """FAISS DB Store Class.

    Using FAISS as an in-memory Document Vector Store.

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
        self.index_path: PurePath = kwargs.pop('index_path', 'faiss_index')
        if not self.index_path.exists():
            self.index_path.mkdir(exist_ok=True)

    async def connection(self):
        """Initialize FAISS vector store.

        If an index exists, load it; otherwise, create a new FAISS store.
        """
        try:
            index_file = self.index_path.joinpath("index.faiss")
            if not index_file.exists():
                raise FileNotFoundError
            self._connection = FAISS.load_local(
                folder_path=self.index_path,
                embeddings=self._embed_.embedding,
                allow_dangerous_deserialization=True,
                distance_strategy=DistanceStrategy.EUCLIDEAN_DISTANCE
            )
        except FileNotFoundError:
            # Create a new FAISS index if none exists.
            print(len(self._embed_.embedding.embed_query("test")))
            index = faiss.IndexFlatL2(len(self._embed_.embedding.embed_query("test")))
            self._connection = FAISS(
                embedding_function=self._embed_.embedding,
                index=index,
                docstore=InMemoryDocstore(),
                index_to_docstore_id={},
                normalize_L2=True,
                distance_strategy=DistanceStrategy.EUCLIDEAN_DISTANCE
            )
            self._connection.save_local(self.index_path)  # Save the new index
        self._connected = True
        return self._connection

    async def disconnect(self) -> None:
        """Clears FAISS in-memory index."""
        self._connection = None
        self._connected = False

    def get_vector(
        self,
        embedding: Optional[Callable] = None,
    ) -> FAISS:
        """Returns FAISS VectorStore instance."""
        if embedding is not None:
            _embed_ = embedding
        else:
            _embed_ = self.create_embedding(
                embedding_model=self.embedding_model
            )
        return FAISS.load_local(
            folder_path=self.index_path,
            embeddings=_embed_,
            allow_dangerous_deserialization=True,
            distance_strategy=DistanceStrategy.EUCLIDEAN_DISTANCE
        )

    async def from_documents(self, documents: list[Document], **kwargs):
        """Save Documents as Vectors in FAISS."""
        vectordb = await FAISS.afrom_documents(
            documents=documents,
            embedding=self._embed_.embedding,
            allow_dangerous_deserialization=True,
            distance_strategy=DistanceStrategy.EUCLIDEAN_DISTANCE
        )
        vectordb.save_local(self.index_path)  # Persist FAISS index
        return vectordb

    async def add_documents(
        self,
        documents: list,
        embedding: Optional[Callable] = None,
    ) -> bool:
        """Add Documents to FAISS."""
        async with self:
            vector_db = self.get_vector(embedding=embedding)
            await vector_db.aadd_documents(documents=documents)
            vector_db.save_local(self.index_path)  # Save updated index
        return True

    async def update_documents(
        self,
        documents: list,
        embedding: Optional[Callable] = None,
    ) -> bool:
        """
        Update Documents in FAISS (FAISS does not natively support updates).
        """
        async with self:
            vector_db = self.get_vector(embedding=embedding)
            if all('id' in doc for doc in documents):
                ids = [doc.pop('id') for doc in documents]
                vector_db.delete(ids)  # Remove old entries
                await vector_db.aadd_documents(documents=documents)  # Add new versions
                vector_db.save_local(self.index_path)
                return True
            return False

    async def similarity_search(
        self,
        query: str,
        embedding: Optional[Callable] = None,
        limit: int = 2,
    ) -> list:
        """Performs similarity search in FAISS."""
        async with self:
            vector_db = self.get_vector(embedding=embedding)
            return vector_db.similarity_search(query, k=limit)

    def memory_retriever(
        self,
        documents: Optional[list] = None,
        num_results: int = 5
    ) -> VectorStoreRetrieverMemory:
        """Retrieves stored memory-based documents."""
        if not documents:
            documents = []
        vectordb = FAISS.from_documents(
            documents=documents,
            embedding=self._embed_.embedding,
            allow_dangerous_deserialization=True,
            distance_strategy=DistanceStrategy.EUCLIDEAN_DISTANCE
        )
        retriever = FAISS.as_retriever(
            vectordb,
            search_kwargs=dict(k=num_results)
        )
        return VectorStoreRetrieverMemory(retriever=retriever)
