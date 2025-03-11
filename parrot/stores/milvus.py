from collections.abc import Callable
from typing import List, Optional, Union
from uuid import uuid4
from langchain.docstore.document import Document
# Milvus Database
from pymilvus import (
    db,
    connections,
    FieldSchema,
    CollectionSchema,
    DataType,
    Collection,
    MilvusClient
)
from pymilvus.exceptions import MilvusException
from langchain_milvus import Milvus  # pylint: disable=import-error, E0611
from langchain.memory import VectorStoreRetrieverMemory
from navconfig.logging import logging
from .abstract import AbstractStore
from ..conf import (
    MILVUS_HOST,
    MILVUS_PROTOCOL,
    MILVUS_PORT,
    MILVUS_URL,
    MILVUS_TOKEN,
    MILVUS_USER,
    MILVUS_PASSWORD,
    MILVUS_SECURE,
    MILVUS_SERVER_NAME,
    MILVUS_CA_CERT,
    MILVUS_SERVER_CERT,
    MILVUS_SERVER_KEY,
    MILVUS_USE_TLSv2
)


logging.getLogger(name='pymilvus').setLevel(logging.WARNING)

class MilvusConnection:
    """
    Context Manager for Milvus Connections.
    """
    def __init__(self, alias: str = 'default', **kwargs):
        self._connected: bool = False
        self.credentials = kwargs
        self.alias: str = alias

    def connect(self, alias: str = None, **kwargs):
        if not alias:
            alias = self.alias
        conn = connections.connect(
            alias=alias,
            **kwargs
        )
        self._connected = True
        return alias

    def is_connected(self):
        return self._connected

    def close(self, alias: str = None):
        try:
            connections.disconnect(alias=alias)
        finally:
            self._connected = False

    def __enter__(self):
        self.connect(alias=self.alias, **self.credentials)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close(alias=self.alias)
        return self


class MilvusStore(AbstractStore):
    """MilvusStore class.

    Milvus is a Vector Database multi-layered.

    Args:
        host (str): Milvus host.
        port (int): Milvus port.
        url (str): Milvus URL.
    """

    def __init__(
        self,
        embedding_model: Union[dict, str] = None,
        embedding: Union[dict, Callable] = None,
        **kwargs
    ):
        self.host = kwargs.pop("host", MILVUS_HOST)
        self.port = kwargs.pop("port", MILVUS_PORT)
        self.protocol = kwargs.pop("protocol", MILVUS_PROTOCOL)
        self.consistency_level: str = kwargs.pop('consistency_level', 'Session')
        self.create_database: bool = kwargs.pop('create_database', True)
        self.url = kwargs.pop("url", MILVUS_URL)
        self._client_id = kwargs.pop('client_id', 'default')
        super().__init__(embedding_model, embedding, **kwargs)
        if not self.url:
            self.url = f"{self.protocol}://{self.host}:{self.port}"
        else:
            # Extract host and port from URL
            if not self.host:
                self.host = self.url.split("://")[-1].split(":")[0]
            if not self.port:
                self.port = int(self.url.split(":")[-1])
        self.token = kwargs.pop("token", MILVUS_TOKEN)
        # user and password (if required)
        self.user = kwargs.pop(
            "user", MILVUS_USER
        )
        self.password = kwargs.pop(
            "password", MILVUS_PASSWORD
        )
        # SSL/TLS
        self._secure: bool = kwargs.pop('secure', MILVUS_SECURE)
        self._server_name: str = kwargs.pop('server_name', MILVUS_SERVER_NAME)
        self._cert: str = kwargs.pop('server_pem_path', MILVUS_SERVER_CERT)
        self._ca_cert: str = kwargs.pop('ca_pem_path', MILVUS_CA_CERT)
        self._cert_key: str = kwargs.pop('client_key_path', MILVUS_SERVER_KEY)
        # Any other argument will be passed to the Milvus client
        self.credentials = {
            "uri": self.url,
            "host": self.host,
            "port": self.port,
            **kwargs
        }
        if self.token:
            self.credentials['token'] = self.token
        if self.user:
            self.credentials['token'] = f"{self.user}:{self.password}"
        # SSL Security:
        if self._secure is True:
            args = {
                "secure": self._secure,
                "server_name": self._server_name
            }
            if self._cert:
                if MILVUS_USE_TLSv2 is True:
                    args['client_pem_path'] = self._cert
                    args['client_key_path'] = self._cert_key
                else:
                    args["server_pem_path"] = self._cert
            if self._ca_cert:
                args['ca_pem_path'] = self._ca_cert
            self.credentials = {**self.credentials, **args}
        if self.database:
            self.credentials['db_name'] = self.database

    async def connection(self, alias: str = None) -> "MilvusStore":
        """Connects to the Milvus database."""
        self._client_id = alias or uuid4().hex
        _ = connections.connect(
            alias=self._client_id,
            **self.credentials
        )
        try:
            if self.database:
                self.use_database(
                    self.database,
                    alias=self._client_id,
                    create=self.create_database
                )
        except Exception as e:
            self.logger.error(
                f"Cannot create Database {self.database} for alias {self._client_id}: {e}"
            )
        self._connection = MilvusClient(
            **self.credentials
        )
        self._connected = True
        print('Connected to database', self._connection)
        return self

    async def disconnect(self, alias: str = None):
        try:
            a = alias or self._client_id
            connections.disconnect(alias=a)
            self._connection.close()
        except AttributeError:
            pass
        finally:
            self._connection = None
            self.client = None
            self._client_id = None
            self._connected = False

    def use_database(
        self,
        db_name: str,
        alias: str = 'default',
        create: bool = False
    ) -> None:
        try:
            conn = connections.connect(alias, **self.credentials)
        except MilvusException as exc:
            if "database not found" in exc.message:
                self.logger.error(
                    f"Database {db_name} does not exist."
                )
                args = self.credentials.copy()
                del args['db_name']
                db.create_database(db_name, alias=alias, **args)
        # re-connect:
        try:
            _ = connections.connect(alias, **self.credentials)
            if db_name not in db.list_database(using=alias):
                if self.create_database is True or create is True:
                    try:
                        db.create_database(db_name, using=alias, timeout=10)
                        self.logger.notice(
                            f"Database {db_name} created successfully."
                        )
                    except Exception as e:
                        raise ValueError(
                            f"Error creating database: {e}"
                        )
                else:
                    raise ValueError(
                        f"Database {db_name} does not exist."
                    )
        finally:
            connections.disconnect(alias=alias)

    def setup_vector(self):
        self.vector = Milvus(
            self._embed_,
            consistency_level='Bounded',
            connection_args={**self.credentials},
            collection_name=self.collection_name,
        )
        return self.vector

    def get_vectorstore(self):
        return self.get_vector()

    async def collection_exists(self, collection_name: str) -> bool:
        async with self.connection():
            if collection_name in self._connection.list_collections():
                return True
        return False

    def check_state(self, collection_name: str) -> dict:
        return self._connection.get_load_state(
            collection_name=collection_name
        )

    def get_vector(
        self,
        collection: Union[str, None] = None,
        metric_type: str = None,
        index_type: str = None,
        nprobe: int = 32,
        metadata_field: str = None,
        consistency_level: str = 'session'
    ) -> Milvus:
        if not metric_type:
            metric_type = self._metric_type
        if not collection:
            collection = self.collection_name
        if not metric_type:
            metric_type = self._metric_type or 'COSINE'
        _idx = index_type or self._index_type
        _search = {
            "search_params": {
                "metric_type": metric_type,
                "index_type": _idx,
                "params": {"nprobe": nprobe, "nlist": 1024},
            }
        }
        if metadata_field:
            # document_meta
            _search['metadata_field'] = metadata_field
        if self._embed_ is None:
            self._embed_ = self.create_embedding(
                embedding_model=self.embedding_model
            )
        return Milvus(
            embedding_function=self._embed_.embedding,
            collection_name=collection,
            consistency_level=consistency_level,
            connection_args={
                **self.credentials
            },
            primary_field='pk',
            text_field='text',
            vector_field='vector',
            **_search
        )

    def search(
        self,
        payload: Union[dict, list],
        collection: Union[str, None] = None,
        limit: Optional[int] = None
    ) -> list:
        args = {}
        if collection is None:
            collection = self.collection_name
        if limit is not None:
            args = {"limit": limit}
        if isinstance(payload, dict):
            payload = [payload]
        result = self._connection.search(
            collection_name=collection,
            data=payload,
            **args
        )
        return result

    def memory_retriever(self, documents: List[Document], num_results: int  = 5) -> VectorStoreRetrieverMemory:
        vectordb = Milvus.from_documents(
            documents or [],
            self._embed_,
            connection_args={**self.credentials}
        )
        retriever = Milvus.as_retriever(
            vectordb,
            search_kwargs=dict(k=num_results)
        )
        return VectorStoreRetrieverMemory(retriever=retriever)

    def save_context(self, memory: VectorStoreRetrieverMemory, context: list) -> None:
        for val in context:
            memory.save_context(val)

    async def similarity_search(
        self,
        query: str,
        collection: Union[str, None] = None,
        limit: int = 2,
        consistency_level: str = 'Bounded'
    ) -> list:
        if collection is None:
            collection = self.collection_name
        if self._embed_ is None:
            _embed_ = self.create_embedding(
                embedding_model=self.embedding_model
            )
        else:
            _embed_ = self._embed_
        vector_db = Milvus(
            embedding_function=_embed_,
            collection_name=collection,
            consistency_level=consistency_level,
            connection_args={
                **self.credentials
            },
            primary_field='pk',
            text_field='text',
            vector_field='vector'
        )
        return await vector_db.asimilarity_search(query, k=limit)

    async def insert(self, collection: str, embeddings: list) -> dict:
        if not collection:
            collection = self.collection_name
        async with self:
            # create the collection object from milvus
            if self._connection.has_collection(collection):
                schema = self._connection.describe_collection(collection)
                if schema.params['dimension']!= embeddings[0].shape[0]:
                    raise ValueError(
                        f"Invalid dimension: expected {schema.params['dimension']}, got {embeddings[0].shape[0]}"
                    )
                self._connection.upsert(collection, embeddings)
            else:
                raise RuntimeError(
                    f"Collection {collection} does not exist."
                )

    async def from_documents(self, documents: list[Document], collection: str = None, **kwargs):
        """
        Save Documents as Vectors in Milvus.
        """
        if not collection:
            collection = self.collection_name
        vectordb = await Milvus.afrom_documents(
            documents=documents,
            embedding=self._embed_,
            connection_args={**self.credentials},
            collection_name=collection
        )
        return vectordb

    async def add_documents(self, documents: list[Document], collection: str = None, **kwargs):
        """
        Add Documents as Vectors in Milvus.
        """
        if not collection:
            collection = self.collection_name
        async with self:
            # create the collection object from milvus
            vectordb = self.get_vector(collection=collection, **kwargs)
            await vectordb.aadd_documents(documents)
