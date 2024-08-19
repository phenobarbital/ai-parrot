from abc import ABC, abstractmethod
from typing import Union, Any
from collections.abc import Callable
import torch
from langchain_huggingface import (
    HuggingFaceEmbeddings
)
from langchain_community.embeddings import (
    HuggingFaceBgeEmbeddings
)
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from navconfig.logging import logging
from ..conf import (
    EMBEDDING_DEVICE,
    EMBEDDING_DEFAULT_MODEL,
    CUDA_DEFAULT_DEVICE,
    MAX_BATCH_SIZE
)


class AbstractStore(ABC):
    """AbstractStore class.

    Args:
        embeddings (str): Embeddings.
    """

    def __init__(self, embeddings: Union[str, Callable] = None, **kwargs):
        self.client: Callable = None
        self.vector: Callable = None
        self._embed_: Callable = None
        self._connected: bool = False
        self.use_bge: bool = kwargs.pop("use_bge", False)
        self.fastembed: bool = kwargs.pop("use_fastembed", False)
        self.embedding_name: str = kwargs.pop('embedding_name', EMBEDDING_DEFAULT_MODEL)
        self.dimension: int = kwargs.pop("dimension", 768)
        self._metric_type: str = kwargs.pop("metric_type", 'COSINE')
        self._index_type: str = kwargs.pop("index_type", 'IVF_FLAT')
        self.database: str = kwargs.pop('database', '')
        self.collection = kwargs.pop("collection_name", "my_collection")
        self.index_name = kwargs.pop("index_name", "my_index")
        if embeddings is not None:
            if isinstance(embeddings, str):
                self.embedding_name = embeddings
            else:
                self._embed_ = embeddings
        self.logger = logging.getLogger(f"Store.{__name__}")
        # client
        self._client = None
        self._client_id = None

    @property
    def connected(self) -> bool:
        return self._connected

    async def __aenter__(self):
        try:
            self.tensor = torch.randn(1000, 1000).cuda()
        except RuntimeError:
            self.tensor = None
        if self._embed_ is None:
            self._embed_ = self.create_embedding(
                model_name=self.embedding_name
            )
        self._client, self._client_id = self.connect()
        return self

    @abstractmethod
    def connect(self):
        pass

    def __enter__(self):
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
            torch.cuda.empty_cache()
        except RuntimeError:
            pass

    def __exit__(self, exc_type, exc_value, traceback):
        # closing Embedding
        self._embed_ = None
        try:
            torch.cuda.empty_cache()
        except RuntimeError:
            pass

    @abstractmethod
    def get_vector(self):
        pass

    @abstractmethod
    async def load_documents(
        self,
        documents: list,
        collection: str = None
    ):
        pass

    @abstractmethod
    def upsert(self, payload: dict, collection_name: str = None) -> None:
        pass

    @abstractmethod
    def search(self, payload: dict, collection_name: str = None) -> dict:
        pass

    @abstractmethod
    async def delete_collection(self, collection_name: str = None) -> dict:
        pass

    @abstractmethod
    async def create_collection(self, collection_name: str, document: Any) -> dict:
        pass

    def create_embedding(
        self,
        model_name: str = None
    ):
        encode_kwargs: str = {
            'normalize_embeddings': True,
            "batch_size": MAX_BATCH_SIZE
        }
        if torch.backends.mps.is_available():
            # Use CUDA Multi-Processing Service if available
            device = torch.device("mps")
        elif torch.cuda.is_available():
            # Use CUDA GPU if available
            device = torch.device(
                f'cuda:{CUDA_DEFAULT_DEVICE}'
            )
        elif EMBEDDING_DEVICE == 'cuda':
            device = torch.device(
                f'cuda:{CUDA_DEFAULT_DEVICE}'
            )
        else:
            device = torch.device(EMBEDDING_DEVICE)
        model_kwargs: str = {'device': device}
        if model_name is None:
            model_name = EMBEDDING_DEFAULT_MODEL
        if self.use_bge is True:
            return HuggingFaceBgeEmbeddings(
                model_name=model_name,
                model_kwargs=model_kwargs,
                encode_kwargs=encode_kwargs
            )
        if self.fastembed is True:
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

    def get_default_embedding(
        self,
        model_name: str = EMBEDDING_DEFAULT_MODEL
    ):
        return self.create_embedding(model_name=model_name)
