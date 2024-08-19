from typing import Optional, Union, Any
import asyncio
import uuid
import torch
from pymilvus import (
    MilvusClient,
    Collection,
    FieldSchema,
    CollectionSchema,
    DataType,
    connections,
    db
)
from pymilvus.exceptions import MilvusException
from langchain_milvus import Milvus  # pylint: disable=import-error, E0611
from langchain.memory import VectorStoreRetrieverMemory
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


class MilvusConnection:
    """
    Context Manager for Milvus Connections.
    """
    def __init__(self, alias: str = 'default', **kwargs):
        self._connected: bool = False
        self.kwargs = kwargs
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
        self.connect(alias=self.alias, **self.kwargs)
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

    def __init__(self, embeddings = None, **kwargs):
        super().__init__(embeddings, **kwargs)
        self.use_bge: bool = kwargs.pop("use_bge", False)
        self.fastembed: bool = kwargs.pop("use_fastembed", False)
        self.database: str = kwargs.pop('database', '')
        self.collection = kwargs.pop('collection_name', '')
        self.dimension: int = kwargs.pop("dimension", 768)
        self._metric_type: str = kwargs.pop("metric_type", 'COSINE')
        self._index_type: str = kwargs.pop("index_type", 'IVF_FLAT')
        self.host = kwargs.pop("host", MILVUS_HOST)
        self.port = kwargs.pop("port", MILVUS_PORT)
        self.protocol = kwargs.pop("protocol", MILVUS_PROTOCOL)
        self.create_database: bool = kwargs.pop('create_database', True)
        self.url = kwargs.pop("url", MILVUS_URL)
        self._client_id = kwargs.pop('client_id', 'default')
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
        self.user = kwargs.pop("user", MILVUS_USER)
        self.password = kwargs.pop("password", MILVUS_PASSWORD)
        # SSL/TLS
        self._secure: bool = kwargs.pop('secure', MILVUS_SECURE)
        self._server_name: str = kwargs.pop('server_name', MILVUS_SERVER_NAME)
        self._cert: str = kwargs.pop('server_pem_path', MILVUS_SERVER_CERT)
        self._ca_cert: str = kwargs.pop('ca_pem_path', MILVUS_CA_CERT)
        self._cert_key: str = kwargs.pop('client_key_path', MILVUS_SERVER_KEY)
        # Any other argument will be passed to the Milvus client
        self.kwargs = {
            "uri": self.url,
            "host": self.host,
            "port": self.port,
            **kwargs
        }
        if self.token:
            self.kwargs['token'] = self.token
        if self.user:
            self.kwargs['token'] = f"{self.user}:{self.password}"
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
            self.kwargs = {**self.kwargs, **args}
        # 1. Check if database exists:
        if self.database:
            self.kwargs['db_name'] = self.database
            self.use_database(
                self.database,
                create=self.create_database
            )

    async def __aenter__(self):
        try:
            self.tensor = torch.randn(1000, 1000).cuda()
        except RuntimeError:
            self.tensor = None
        if self._embed_ is None:
            self._embed_ = self.create_embedding(
                model_name=self.embedding_name
            )
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        # closing Embedding
        self._embed_ = None
        del self.tensor
        try:
            self.close(alias=self._client_id)
            torch.cuda.empty_cache()
        except RuntimeError:
            pass

    def connection(self, alias: str = None):
        if not alias:
            # self._client_id = str(uuid.uuid4())
            self._client_id = 'uri-connection'
        else:
            self._client_id = alias
        # making the connection:
        self._client, self._client_id = self.connect(
            alias=self._client_id
        )
        return self

    def connect(self, alias: str = None) -> tuple:
        # 1. Set up a pyMilvus default connection
        # Unique connection:
        if not alias:
            alias = "default"
        _ = connections.connect(
            alias=alias,
            **self.kwargs
        )
        client = MilvusClient(
            **self.kwargs
        )
        self._connected = True
        return client, alias

    def close(self, alias: str = "default"):
        connections.disconnect(alias=alias)
        try:
            self._client.close()
        finally:
            self._connected = False

    def create_db(self, db_name: str, alias: str = 'default', **kwargs) -> bool:
        args = {
            "uri": self.url,
            "host": self.host,
            "port": self.port,
            **kwargs
        }
        try:
            conn = connections.connect(alias, **args)
            db.create_database(db_name)
            self.logger.notice(
                f"Database {db_name} created successfully."
            )
        except Exception as e:
            raise ValueError(
                f"Error creating database: {e}"
            )
        finally:
            connections.disconnect(alias="uri-connection")

    def use_database(
        self,
        db_name: str,
        alias:str = 'default',
        create: bool = False
    ) -> None:
        try:
            conn = connections.connect(alias, **self.kwargs)
        except MilvusException as exc:
            if "database not found" in exc.message:
                args = self.kwargs.copy()
                del args['db_name']
                self.create_db(db_name, alias=alias, **args)
        # re-connect:
        try:
            _ = connections.connect(alias, **self.kwargs)
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
            connection_args={**self.kwargs},
            collection_name=self.collection,
        )
        return self.vector

    def get_vectorstore(self):
        return self.get_vector()

    def collection_exists(self, collection_name: str) -> bool:
        if collection_name in self._client.list_collections():
            return True
        return False

    def check_state(self, collection_name: str) -> dict:
        return self._client.get_load_state(collection_name=collection_name)

    async def delete_collection(self, collection: str = None) -> dict:
        self._client.drop_collection(
            collection_name=collection
        )

    async def create_collection(
        self,
        collection_name: str,
        document: Any = None,
        dimension: int = 768,
        index_type: str = None,
        metric_type: str = None,
        schema_type: str = 'default',
        metadata_field: str = None,
        **kwargs
    ) -> dict:
        """create_collection.

        Create a Schema (Milvus Collection) on the Current Database.

        Args:
            collection_name (str): Collection Name.
            document (Any): List of Documents.
            dimension (int, optional): Vector Dimension. Defaults to 768.
            index_type (str, optional): Default index type of Vector Field. Defaults to "HNSW".
            metric_type (str, optional): Default Metric for Vector Index. Defaults to "L2".
            schema_type (str, optional): Description of Model. Defaults to 'default'.

        Returns:
            dict: _description_
        """
        # Check if collection exists:
        if self.collection_exists(collection_name):
            self.logger.warning(
                f"Collection {collection_name} already exists."
            )
            return None
        idx_params = {}
        if not index_type:
            index_type = self._index_type
        if index_type == 'HNSW':
            idx_params = {
                "M": 36,
                "efConstruction": 1024
            }
        elif index_type in ('IVF_FLAT', 'SCANN', 'IVF_SQ8'):
            idx_params = {
                "nlist": 1024
            }
        elif index_type in ('IVF_PQ'):
            idx_params = {
                "nlist": 1024,
                "m": 16
            }
        if not metric_type:
            metric_type = self._metric_type  # default metric type
        if schema_type == 'default':
            # Default Collection for all loaders:
            schema = MilvusClient.create_schema(
                auto_id=False,
                enable_dynamic_field=True,
                description=collection_name
            )
            schema.add_field(
                field_name="pk",
                datatype=DataType.INT64,
                is_primary=True,
                auto_id=True,
                max_length=100
            )
            schema.add_field(
                field_name="index",
                datatype=DataType.VARCHAR,
                max_length=65535
            )
            schema.add_field(
                field_name="url",
                datatype=DataType.VARCHAR,
                max_length=65535
            )
            schema.add_field(
                field_name="source",
                datatype=DataType.VARCHAR,
                max_length=65535
            )
            schema.add_field(
                field_name="filename",
                datatype=DataType.VARCHAR,
                max_length=65535
            )
            schema.add_field(
                field_name="question",
                datatype=DataType.VARCHAR,
                max_length=65535
            )
            schema.add_field(
                field_name="answer",
                datatype=DataType.VARCHAR,
                max_length=65535
            )
            schema.add_field(
                field_name="source_type",
                datatype=DataType.VARCHAR,
                max_length=128
            )
            schema.add_field(
                field_name="type",
                datatype=DataType.VARCHAR,
                max_length=65535
            )
            schema.add_field(
                field_name="text",
                datatype=DataType.VARCHAR,
                description="Text",
                max_length=65535
            )
            schema.add_field(
                field_name="summary",
                datatype=DataType.VARCHAR,
                description="Summary (refine resume)",
                max_length=65535
            )
            schema.add_field(
                field_name="vector",
                datatype=DataType.FLOAT_VECTOR,
                dim=dimension,
                description="vector"
            )
            # schema.add_field(
            #     field_name="embedding",
            #     datatype=DataType.FLOAT_VECTOR,
            #     dim=dimension,
            #     description="Binary Embeddings"
            # )
            schema.add_field(
                field_name="document_meta",
                datatype=DataType.JSON,
                description="Custom Metadata information"
            )
            index_params = self._client.prepare_index_params()
            index_params.add_index(
                field_name="pk",
                index_type="STL_SORT"
            )
            index_params.add_index(
                field_name="text",
                index_type="marisa-trie"
            )
            index_params.add_index(
                field_name="summary",
                index_type="marisa-trie"
            )
            index_params.add_index(
                field_name="vector",
                index_type=index_type,
                metric_type=metric_type,
                params=idx_params
            )
            self._client.create_collection(
                collection_name=collection_name,
                schema=schema,
                index_params=index_params,
                num_shards=2
            )
            await asyncio.sleep(2)
            res = self._client.get_load_state(
                collection_name=collection_name
            )
            return None
        else:
            self._client.create_collection(
                collection_name=collection_name,
                dimension=dimension
            )
            if metadata_field:
                kwargs['metadata_field'] = metadata_field
            # Here using drop_old=True to force recreate based on the first document
            docstore = Milvus.from_documents(
                [document],  # Only the first document
                self._embed_,
                connection_args={**self.kwargs},
                collection_name=collection_name,
                drop_old=True,
                # consistency_level='Session',
                primary_field='pk',
                text_field='text',
                vector_field='vector',
                **kwargs
            )
            return docstore

    async def load_documents(
        self,
        documents: list,
        collection: str = None,
        upsert: bool = False,
        attribute: str = 'source_type',
        metadata_field: str = None,
        **kwargs
    ):
        if not collection:
            collection = self.collection
        try:
            tensor = torch.randn(1000, 1000).cuda()
        except Exception:
            tensor = None
        if upsert is True:
            # get first document
            doc = documents[0]
            # getting source type:
            doc_type = doc.metadata.get('attribute', None)
            if attribute:
                deleted = self._client.delete(
                    collection_name=collection,
                    filter=f'{attribute} == "{doc_type}"'
                )
                self.logger.notice(
                    f"Deleted documents with {attribute} {attribute}: {deleted}"
                )
        if metadata_field:
            # document_meta
            kwargs['metadata_field'] = metadata_field
        docstore = Milvus.from_documents(
            documents,
            self._embed_,
            connection_args={**self.kwargs},
            collection_name=collection,
            consistency_level='Bounded',
            drop_old=False,
            primary_field='pk',
            text_field='text',
            vector_field='vector',
            **kwargs
        )
        del tensor
        return docstore

    def upsert(self, payload: dict, collection: str = None) -> None:
        pass

    def insert(
        self,
        payload: Union[dict, list],
        collection: Union[str, None] = None
    ) -> dict:
        if collection is None:
            collection = self.collection
        result = self._client.insert(
            collection_name=collection,
            data=payload
        )
        collection.flush()
        return result

    def get_vector(
        self,
        collection: Union[str, None] = None,
        metric_type: str = None,
        nprobe: int = 32,
        metadata_field: str = None,
        consistency_level: str = 'session'
    ) -> Milvus:
        if not metric_type:
            metric_type = self._metric_type
        if not collection:
            collection = self.collection
        _search = {
            "search_params": {
                "metric_type": metric_type,
                "params": {"nprobe": nprobe, "nlist": 1024},
            }
        }
        if metadata_field:
            # document_meta
            _search['metadata_field'] = metadata_field
        _embed_ = self.create_embedding(
            model_name=self.embedding_name
        )
        return Milvus(
            embedding_function=_embed_,
            collection_name=collection,
            consistency_level=consistency_level,
            connection_args={
                **self.kwargs
            },
            primary_field='pk',
            text_field='text',
            vector_field='vector',
            **_search
        )

    def similarity_search(
        self,
        query: str,
        collection: Union[str, None] = None,
        limit: int = 2,
        consistency_level: str = 'Bounded'
    ) -> list:
        if collection is None:
            collection = self.collection
        if self._embed_ is None:
            _embed_ = self.create_embedding(
                model_name=self.embedding_name
            )
        else:
            _embed_ = self._embed_
        vector_db = Milvus(
            embedding_function=_embed_,
            collection_name=collection,
            consistency_level=consistency_level,
            connection_args={
                **self.kwargs
            },
            primary_field='pk',
            text_field='text',
            vector_field='vector'
        )
        return vector_db.similarity_search(query, k=limit)

    def search(
        self,
        payload: Union[dict, list],
        collection: Union[str, None] = None,
        limit: Optional[int] = None
    ) -> list:
        args = {}
        if collection is None:
            collection = self.collection
        if limit is not None:
            args = {"limit": limit}
        if isinstance(payload, dict):
            payload = [payload]
        result = self._client.search(
            collection_name=collection,
            data=payload,
            **args
        )
        return result

    def memory_retriever(self, num_results: int  = 5) -> VectorStoreRetrieverMemory:
        vectordb = Milvus.from_documents(
            {},
            self._embed_,
            connection_args={**self.kwargs}
        )
        retriever = Milvus.as_retriever(
            vectordb,
            search_kwargs=dict(k=num_results)
        )
        return VectorStoreRetrieverMemory(retriever=retriever)

    def save_context(self, memory: VectorStoreRetrieverMemory, context: list) -> None:
        for val in context:
            memory.save_context(val)
