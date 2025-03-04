from collections.abc import Callable
from typing import Optional, Union
from uuid import uuid4
import logging
from langchain.docstore.document import Document
from langchain.memory import VectorStoreRetrieverMemory
import chromadb
from langchain_chroma import Chroma
from .abstract import AbstractStore
from ..conf import CHROMADB_HOST, CHROMADB_PORT


logging.getLogger('chromadb').setLevel(logging.INFO)


class ChromaStore(AbstractStore):
    """Chroma DB Store Class.

    Using Chroma as Document Vector Store.

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
        self.database_path: str = kwargs.pop('database_path', 'chroma.db')
        self._ephemeral: bool = kwargs.pop('ephemeral', False)
        self._local: bool = kwargs.pop('local', False)
        self.host = kwargs.pop("host", CHROMADB_HOST)
        self.port = kwargs.pop("port", CHROMADB_PORT)
        self._collection = None

    async def connection(self):
        """Connection to ChromaDB.

        Args:
            alias (str): Database alias.

        Returns:
            Callable: ChromaDB connection.

        """
        if self._ephemeral:
            self._connection = chromadb.Client()
        elif self._local:
            self._connection = chromadb.PersistentClient(
                path=self.database_path,
                database=self.database,
            )
        else:
            # Client-Server Connection:
            self._connection = chromadb.HttpClient(
                host=self.host,
                port=self.port,
                database=self.database,
            )
        self._collection = self._connection.get_or_create_collection(self.collection_name)
        self._connected = True
        return self._connection

    async def disconnect(self) -> None:
        """
        Closing the Connection on ChromaDB
        """
        self._connection = None
        self._connected = False

    def get_vector(
        self,
        collection: Union[str, None] = None,
        embedding: Optional[Callable] = None,
    ) -> Chroma:

        if not collection:
            collection = self.collection_name
        if embedding is not None:
            _embed_ = embedding
        else:
            _embed_ = self._embed_ or self.create_embedding(
                embedding_model=self.embedding_model
            )
        return Chroma(
            collection_name=self.collection_name,
            embedding_function=_embed_.embedding,
            client=self._connection,
            create_collection_if_not_exists=True,
        )

    async def from_documents(self, documents: list[Document], collection: str = None, **kwargs):
        """
        Save Documents as Vectors in Chroma.
        """
        vectordb = await Chroma.afrom_documents(
            documents=documents,
            embedding=self._embed_.embedding,
            connection=self._connection,
        )
        return vectordb


    async def add_texts(self, objects: list, collection: str = None):
        """
        Add Texts to ChromaDB
        """
        async with self:
            collection = self._connection.get_or_create_collection(collection)
            for i, doc in enumerate(objects):
                collection.add(ids=[str(i)], documents=[doc])
        return True

    async def add_documents(
        self,
        documents: list,
        collection: str = None,
        embedding: Optional[Callable] = None,
    ) -> bool:
        """Add Documents to ChromaDB"""

        if collection is None:
            collection = self.collection_name

        async with self:
            collection_obj = self._connection.get_or_create_collection(collection)
            uuids = [str(uuid4()) for _ in range(len(documents))]
            vector_db = self.get_vector(collection=collection, embedding=embedding)
            await vector_db.aadd_documents(documents=documents, ids=uuids)

        return True


    async def update_documents(
        self,
        documents: list,
        collection: str = None,
        embedding: Optional[Callable] = None,
    )   -> bool:
        """
        Update Documents to ChromaDB
        """
        async with self:
            collection = self._connection.get_or_create_collection(collection)
            vector_db = self.get_vector(collection=collection, embedding=embedding)
            # Split the documents into ids and documents
            if all('id' in doc for doc in documents):
                ids = [doc.pop('id') for doc in documents]
                vector_db.update_documents(documents=documents, ids=ids)
                return True
            return False

    async def similarity_search(
        self,
        query: str,
        collection: Union[str, None] = None,
        embedding: Optional[Callable] = None,
        limit: int = 2,
        filter: Optional[dict] = None,
    ) -> list:
        if collection is None:
            collection = self.collection_name
        async with self:
            vector_db = self.get_vector(collection=collection, embedding=embedding)
            return vector_db.similarity_search(query, k=limit, filter=filter)

    def memory_retriever(
        self,
        documents: Optional[list] = None,
        num_results: int  = 5
    ) -> VectorStoreRetrieverMemory:
        if not documents:
            documents = []
        vectordb = Chroma.from_documents(
            documents=documents,
            embedding=self._embed_.embedding,
            connection=self._connection,
        )
        retriever = Chroma.as_retriever(
            vectordb,
            search_kwargs=dict(k=num_results)
        )
        return VectorStoreRetrieverMemory(retriever=retriever)
