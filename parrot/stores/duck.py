from collections.abc import Callable
from typing import Optional, Union
import duckdb
from langchain.docstore.document import Document
from langchain.memory import VectorStoreRetrieverMemory
from langchain_community.vectorstores import DuckDB
from .abstract import AbstractStore


class DuckDBStore(AbstractStore):
    """DuckDB Store Class.

    Using DuckDB as Document Vector Store.

    """
    default_config: dict ={
        "enable_external_access": "false",
        "autoinstall_known_extensions": "false",
        "autoload_known_extensions": "false"
    }

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
        self.credentials = {
            "database": self.database,
        }

        config: dict = kwargs.pop("config", {})
        self.config = {
            **self.default_config,
            **config
        }

    async def connection(self, alias: str = None):
        """Connection to DuckDB.

        Args:
            alias (str): Database alias.

        Returns:
            Callable: DuckDB connection.

        """
        self._connection = duckdb.connect(**self.credentials, config=self.config)
        self._connected = True
        return self._connection

    async def disconnect(self) -> None:
        """
        Closing the Connection on DuckDB
        """
        try:
            if self._connection:
                self._connection.close()
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
        metadata_field: str = 'id',
        text_field: str = 'text',
        vector_key: str = 'vector',
    ) -> DuckDB:

        if not collection:
            collection = self.collection_name
        if embedding is not None:
            _embed_ = embedding
        else:
            _embed_ = self.create_embedding(
                embedding_model=self.embedding_model
            )
        return DuckDB(
            connection=self._connection,
            table_name=collection,
            embedding=_embed_,
            vector_key=vector_key,
            text_key=text_field,
            id_key=metadata_field
        )


    async def add_texts(self, objects: list, collection: str = None):
        """
        Add Texts to DuckDB
        """
        async with self:
            store = self.get_vector(collection=collection)
            store.add_texts(objects)
        return True

    async def similarity_search(
        self,
        query: str,
        collection: Union[str, None] = None,
        embedding: Optional[Callable] = None,
        limit: int = 2,
    ) -> list:
        if collection is None:
            collection = self.collection_name
        async with self:
            vector_db = self.get_vector(collection=collection, embedding=embedding)
            return await vector_db.asimilarity_search(query, k=limit)

    def memory_retriever(
        self,
        documents: Optional[list] = None,
        num_results: int  = 5
    ) -> VectorStoreRetrieverMemory:
        if not documents:
            documents = []
        vectordb = DuckDB.from_documents(
            documents=documents,
            embedding=self._embed_.embedding,
            connection=self._connection,
        )
        retriever = DuckDB.as_retriever(
            vectordb,
            search_kwargs=dict(k=num_results)
        )
        return VectorStoreRetrieverMemory(retriever=retriever)

    async def from_documents(self, documents: list[Document], collection: str = None, **kwargs):
        """
        Save Documents as Vectors in DuckDB.
        """
        if not collection:
            collection = self.collection_name
        vectordb = await DuckDB.afrom_documents(
            documents,
            embedding=self._embed_.embedding,
            connection=self._connection,
        )
        return vectordb

    async def add_documents(self, documents: list[Document], collection: str = None, **kwargs):
        """
        Add Documents as Vectors in DuckDB.
        """
        if not collection:
            collection = self.collection_name
        vectordb = self.get_vector(collection=collection)
        result = await vectordb.aadd_documents(
            documents=documents
        )
        return result
