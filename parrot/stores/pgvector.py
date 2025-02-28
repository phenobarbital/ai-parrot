from typing import List, Union, Optional
from collections.abc import Callable
from langchain.docstore.document import Document
from langchain.memory import VectorStoreRetrieverMemory
from langchain_community.vectorstores.utils import DistanceStrategy
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from langchain_postgres.vectorstores import PGVector
from .abstract import AbstractStore


class PgvectorStore(AbstractStore):
    """Pgvector Store Class.

    Using PostgreSQL + PgVector to saving vectors in database.
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
        self.dsn = kwargs.get('dsn', self.database)

    async def connection(self, alias: str = None):
        """Connection to DuckDB.

        Args:
            alias (str): Database alias.

        Returns:
            Callable: DuckDB connection.

        """
        self._connection = create_async_engine(self.dsn, future=True, echo=False)
        self._connected = True
        return self._connection

    async def disconnect(self) -> None:
        """
        Closing the Connection on DuckDB
        """
        try:
            if self._connection:
                await self._connection.dispose()
        except Exception as err:
            raise RuntimeError(
                message=f"{__name__!s}: Closing Error: {err!s}"
            ) from err
        finally:
            self._connection = None
            self._connected = False

    def get_vector(
        self,
        collection: Union[str, None] = None,
        embedding: Optional[Callable] = None,
        **kwargs
    ) -> PGVector:

        if not collection:
            collection = self.collection_name
        if embedding is not None:
            _embed_ = embedding
        else:
            _embed_ = self.create_embedding(
                embedding_model=self.embedding_model
            )
        return PGVector(
            connection=self._connection,
            collection_name=collection,
            embedding_length=self.dimension,
            embeddings=_embed_,
            logger=self.logger,
            use_jsonb=True,
            create_extension=True,
            async_mode=True,
            **kwargs
        )

    def memory_retriever(
        self,
        documents: Optional[List[Document]] = None,
        num_results: int  = 5
    ) -> VectorStoreRetrieverMemory:
        _embed_ = self._embed_ or self.create_embedding(
                embedding_model=self.embedding_model
        )
        vectordb = PGVector.from_documents(
            documents or {},
            embedding=_embed_,
            connection=self._connection,
            collection_name=self.collection_name,
            embedding_length=self.dimension,
            use_jsonb=True,
            create_extension=True,
            async_mode=True
        )
        retriever = PGVector.as_retriever(
            vectordb,
            search_kwargs=dict(k=num_results)
        )
        return VectorStoreRetrieverMemory(retriever=retriever)

    async def from_documents(
        self,
        documents: List[Document],
        collection: Union[str, None] = None,
        **kwargs
    ) -> None:
        """Save Documents as Vectors in VectorStore."""
        _embed_ = self._embed_ or self.create_embedding(
                embedding_model=self.embedding_model
        )
        if not collection:
            collection = self.collection_name
        vectordb = await PGVector.afrom_documents(
            documents,
            connection=self._connection,
            collection_name=collection,
            embedding=_embed_,
            embedding_length=self.dimension,
            use_jsonb=True,
            create_extension=True,
            async_mode=True,
            distance_strategy=DistanceStrategy.EUCLIDEAN_DISTANCE
        )
        return vectordb

    async def add_documents(
        self,
        documents: List[Document],
        collection: Union[str, None] = None,
        **kwargs
    ) -> None:
        """Save Documents as Vectors in VectorStore."""
        _embed_ = self._embed_ or self.create_embedding(
                embedding_model=self.embedding_model
        )
        if not collection:
            collection = self.collection_name
        vectordb = self.get_vector(collection=collection, embedding=_embed_)
        # Asynchronously add documents to PGVector
        await vectordb.aadd_documents(documents)

    async def similarity_search(
        self,
        query: str,
        collection: Union[str, None] = None,
        limit: int = 2,
        filter: Optional[dict] = None
    ) -> List[Document]:
        """Search for similar documents in VectorStore."""
        if collection is None:
            collection = self.collection_name
        async with self:
            vector_db = self.get_vector(collection=collection)
            return await vector_db.asimilarity_search(
                query,
                k=limit,
                filter=filter
            )
