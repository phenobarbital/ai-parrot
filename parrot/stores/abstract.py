from abc import ABC, abstractmethod
from typing import Union
from collections.abc import Callable
from navconfig.logging import logging
from ..conf import (
    EMBEDDING_DEFAULT_MODEL
)


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
                    'model_type': 'transformers'
                }
            elif isinstance(embedding_model, dict):
                self.embedding_model = embedding_model
            else:
                raise ValueError(
                    "Embedding Model must be a string or a dictionary."
                )
        # Database Information:
        self.collection_name: str = kwargs.pop('collection_name', 'my_collection')
        self.dimension: int = kwargs.pop("dimension", 768)
        self._metric_type: str = kwargs.pop("metric_type", 'COSINE')
        self._index_type: str = kwargs.pop("index_type", 'IVF_FLAT')
        self.database: str = kwargs.pop('database', '')
        self.index_name = kwargs.pop("index_name", "my_index")
        if embedding is not None:
            if isinstance(embedding, str):
                self.embedding_model = {
                    'model_name': embedding,
                    'model_type': 'transformers'
                }
            elif isinstance(embedding, dict):
                self.embedding_model = embedding
            else:
                # is a callable:
                self.embedding_model = {
                    'model_name': EMBEDDING_DEFAULT_MODEL,
                    'model_type': 'transformers'
                }
                self._embed_ = embedding
        self.logger = logging.getLogger(
            f"Store.{__name__}"
        )
        # Client Connection (if required):
        self._connection = None

    @property
    def connected(self) -> bool:
        return self._connected

    @abstractmethod
    async def connection(self) -> tuple:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    # Async Context Manager
    async def __aenter__(self):
        if self._embed_ is None:
            self._embed_ = self.create_embedding(
                embedding_model=self.embedding_model
            )
        await self.connection()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        # closing Embedding
        self._embed_ = None
        try:
            await self.disconnect()
        except RuntimeError:
            pass

    @abstractmethod
    def get_vector(self):
        pass

    @abstractmethod
    def search(self, payload: dict, collection_name: str = None) -> dict:
        pass

    @abstractmethod
    def get_device(self, device_type: str = None, **kwargs):
        """
        Get Default Device to use in Embedding Transformers.
        """
        pass

    @abstractmethod
    def create_embedding(
        self,
        embedding_model: dict
    ):
        """
        Create Embedding Model.
        """
        pass

    def get_default_embedding(self):
        embed_model = {
            'model_name': EMBEDDING_DEFAULT_MODEL,
            'model_type': 'transformers'
        }
        return self.create_embedding(
            embedding_model=embed_model
        )
