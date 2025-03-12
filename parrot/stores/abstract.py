from abc import ABC, abstractmethod
from typing import List, Union
import importlib
from collections.abc import Callable
from langchain.docstore.document import Document
from langchain_core.vectorstores import VectorStoreRetriever
from navconfig.logging import logging
from ..conf import (
    EMBEDDING_DEFAULT_MODEL
)
from ..exceptions import ConfigError  # pylint: disable=E0611
from .embeddings import supported_embeddings


class AbstractStore(ABC):
    """AbstractStore class.

        Base class for all Database Vector Stores.
    Args:
        embeddings (str): Embedding name.

    Supported Vector Stores:
        - Qdrant
        - Milvus
        - Faiss
        - Chroma
        - PgVector
    """

    def __init__(
        self,
        embedding_model: Union[dict, str] = None,
        embedding: Union[dict, Callable] = None,
        **kwargs
    ):
        self.client: Callable = None
        self.vector: Callable = None
        self._embed_: Callable = None
        self._connected: bool = False
        if embedding_model is not None:
            if isinstance(embedding_model, str):
                self.embedding_model = {
                    'model_name': embedding_model,
                    'model_type': 'huggingface'
                }
            elif isinstance(embedding_model, dict):
                self.embedding_model = embedding_model
            else:
                raise ValueError(
                    "Embedding Model must be a string or a dictionary."
                )
        # Use or not connection to a vector database:
        self._use_database: bool = kwargs.get('use_database', True)
        # Database Information:
        self.collection_name: str = kwargs.get('collection_name', 'my_collection')
        self.dimension: int = kwargs.get("dimension", 768)
        self._metric_type: str = kwargs.get("metric_type", 'COSINE')
        self._index_type: str = kwargs.get("index_type", 'IVF_FLAT')
        self.database: str = kwargs.get('database', '')
        self.index_name = kwargs.get("index_name", "my_index")
        if embedding is not None:
            if isinstance(embedding, str):
                self.embedding_model = {
                    'model_name': embedding,
                    'model_type': 'huggingface'
                }
            elif isinstance(embedding, dict):
                self.embedding_model = embedding
            else:
                # is a callable:
                self.embedding_model = {
                    'model_name': EMBEDDING_DEFAULT_MODEL,
                    'model_type': 'huggingface'
                }
                self._embed_ = embedding
        self.logger = logging.getLogger(
            f"Store.{__name__}"
        )
        # Client Connection (if required):
        self._connection = None
        # Create the Embedding Model:
        self._embed_ = self.create_embedding(
            embedding_model=self.embedding_model
        )

    @property
    def connected(self) -> bool:
        return self._connected

    def is_connected(self):
        return self._connected

    @abstractmethod
    async def connection(self) -> tuple:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    # Async Context Manager
    async def __aenter__(self):
        if self._use_database:
            if not self._connection:
                await self.connection()
        return self

    async def _free_resources(self):
        self._embed_.free()
        self._embed_ = None

    async def __aexit__(self, exc_type, exc_value, traceback):
        # closing Embedding
        try:
            await self.disconnect()
        except RuntimeError:
            pass

    @abstractmethod
    def get_vector(self, metric_type: str = None, **kwargs):
        pass

    def get_vectorstore(self):
        return self.get_vector()

    @abstractmethod
    async def similarity_search(
        self,
        query: str,
        collection: Union[str, None] = None,
        limit: int = 2
    ) -> list:  # noqa
        pass

    @abstractmethod
    async def from_documents(
        self,
        documents: List[Document],
        collection: Union[str, None] = None,
        **kwargs
    ) -> Callable:
        """
        Create Vector Store from Documents.

        Args:
            documents (List[Document]): List of Documents.
            collection (str): Collection Name.
            kwargs: Additional Arguments.

        Returns:
            Callable VectorStore.
        """

    @abstractmethod
    async def add_documents(
        self,
        documents: List[Document],
        collection: Union[str, None] = None,
        **kwargs
    ) -> None:
        """
        Add Documents to Vector Store.

        Args:
            documents (List[Document]): List of Documents.
            collection (str): Collection Name.
            kwargs: Additional Arguments.

        Returns:
            None.
        """

    def create_embedding(
        self,

        embedding_model: dict,
        **kwargs
    ):
        """
        Create Embedding Model.

        Args:
            embedding_model (dict): Embedding Model Configuration.
            kwargs: Additional Arguments.

        Returns:
            Callable: Embedding Model.

        """
        model_type = embedding_model.get('model_type', 'huggingface')
        model_name = embedding_model.get('model_name', EMBEDDING_DEFAULT_MODEL)
        if model_type not in supported_embeddings:
            raise ConfigError(
                f"Embedding Model Type: {model_type} not supported."
            )
        embed_cls = supported_embeddings[model_type]
        cls_path = f".embeddings.{model_type}"  # Relative module path
        try:
            embed_module = importlib.import_module(
                cls_path,
                package=__package__
            )
            embed_obj = getattr(embed_module, embed_cls)
            return embed_obj(
                model_name=model_name,
                **kwargs
            )
        except ImportError as e:
            raise ConfigError(
                f"Error Importing Embedding Model: {model_type}"
            ) from e

    def get_default_embedding(self):
        embed_model = {
            'model_name': EMBEDDING_DEFAULT_MODEL,
            'model_type': 'huggingface'
        }
        return self.create_embedding(
            embedding_model=embed_model
        )

    def generate_embedding(self, documents: List[Document]):
        if not self._embed_:
            self._embed_ = self.get_default_embedding()

        # Using the Embed Model to Generate Embeddings:
        embeddings = self._embed_.embed_documents(documents)
        return embeddings

    def as_retriever(
        self,
        metric_type: str = 'COSINE',
        index_type: str = 'IVF_FLAT',
        search_type: str = 'similarity',
        chain_type: str = 'stuff',
        search_kwargs: dict = None
    ) -> Callable:
        vector = self.get_vector(metric_type=metric_type, index_type=index_type)
        if not vector:
            raise ConfigError(
                "Vector Store is not connected. Check your connection."
            )
        return VectorStoreRetriever(
            vectorstore=vector,
            search_type=search_type,
            chain_type=chain_type,
            search_kwargs=search_kwargs
        )
