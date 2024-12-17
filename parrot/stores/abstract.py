from abc import ABC, abstractmethod
from typing import Union
from collections.abc import Callable
from navconfig.logging import logging
try:
    import torch  # pylint: disable=E0401,C0415  # noqa: F401
    from langchain_huggingface import (
        HuggingFaceEmbeddings
    )
    from langchain_community.embeddings import (
        HuggingFaceBgeEmbeddings
    )
    from langchain_community.embeddings.fastembed import (
        FastEmbedEmbeddings
    )
except ImportError:
    logging.warning(
        f"Unable to import HuggingFace Embeddings, required to use Vector Databases and embeddings."
    )
from ..conf import (
    EMBEDDING_DEVICE,
    EMBEDDING_DEFAULT_MODEL,
    CUDA_DEFAULT_DEVICE,
    MAX_BATCH_SIZE
)


class AbstractStore(ABC):
    """AbstractStore class.

        Base class for all Vector Database Stores.
    Args:
        embeddings (str): Embeddings.
    """
    def __init__(self, embeddings: Union[str, Callable] = None, **kwargs):
        self.client: Callable = None
        self.vector: Callable = None
        self._embed_: Callable = None
        self._connected: bool = False
        self.embedding_model: dict = kwargs.pop('embedding_model', {})
        self.collection_name: str = kwargs.pop('collection_name', 'my_collection')
        self.dimension: int = kwargs.pop("dimension", 768)
        self._metric_type: str = kwargs.pop("metric_type", 'COSINE')
        self._index_type: str = kwargs.pop("index_type", 'IVF_FLAT')
        self.database: str = kwargs.pop('database', '')
        self._use_database: bool = kwargs.pop('use_database', True)
        self.index_name = kwargs.pop("index_name", "my_index")
        if embeddings is not None:
            if isinstance(embeddings, str):
                self.embedding_model = {
                    'model_name': embeddings,
                    'model_type': 'transformers'
                }
            elif isinstance(embeddings, dict):
                self.embedding_model = embeddings
            else:
                # is a callable:
                self.embedding_model = {
                    'model_name': EMBEDDING_DEFAULT_MODEL,
                    'model_type': 'transformers'
                }
                self._embed_ = embeddings
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
        if self._use_database is True:
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
            if self._use_database is True:
                await self.disconnect()
        except RuntimeError:
            pass

    @abstractmethod
    def get_vector(self):
        pass

    @abstractmethod
    def search(self, payload: dict, collection_name: str = None) -> dict:
        pass

    def _get_device(self, device_type: str = None, cuda_number: int = CUDA_DEFAULT_DEVICE):
        """Get Default device for Torch and transformers.

        """
        torch.backends.cudnn.deterministic = True
        if device_type is not None:
            return torch.device(device_type)
        if torch.cuda.is_available():
            # Use CUDA GPU if available
            return torch.device(f'cuda:{cuda_number}')
        if torch.backends.mps.is_available():
            # Use CUDA Multi-Processing Service if available
            return torch.device("mps")
        if EMBEDDING_DEVICE == 'cuda':
            return torch.device(f'cuda:{cuda_number}')
        else:
            return torch.device(EMBEDDING_DEVICE)

    def create_embedding(
        self,
        embedding_model: dict
    ):
        encode_kwargs: str = {
            'normalize_embeddings': True,
            "batch_size": MAX_BATCH_SIZE
        }
        device = self._get_device()
        model_kwargs: str = {'device': device}
        model_name = embedding_model.get('model_name', EMBEDDING_DEFAULT_MODEL)
        model_type = embedding_model.get('model_type', 'transformers')
        if model_type == 'bge':
            return HuggingFaceBgeEmbeddings(
                model_name=model_name,
                model_kwargs=model_kwargs,
                encode_kwargs=encode_kwargs
            )
        if model_type == 'fastembed':
            return FastEmbedEmbeddings(
                model_name=model_name,
                max_length=1024,
                threads=4
            )
        return HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs=model_kwargs,
            encode_kwargs=encode_kwargs
        )

    def get_default_embedding(self):
        embed_model = {
            'model_name': EMBEDDING_DEFAULT_MODEL,
            'model_type': 'transformers'
        }
        return self.create_embedding(
            embedding_model=embed_model
        )
