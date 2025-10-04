from abc import ABC, abstractmethod
from typing import List, Optional, Union, Any
import asyncio
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from navconfig.logging import logging
from ..conf import (
    EMBEDDING_DEVICE,
    CUDA_DEFAULT_DEVICE
)


class EmbeddingModel(ABC):
    """
    Abstract base class for embedding models.
    It ensures that embedding models can be used interchangeably.
    """
    def __init__(self, model_name: str, **kwargs):
        self.model_name = model_name
        self.logger = logging.getLogger(f"parrot.{self.__class__.__name__}")
        self.device, _, self._dtype = self._get_device()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._model_lock = asyncio.Lock()
        self._dimension = None
        self.model = self._create_embedding(
            model_name=self.model_name,
            **kwargs
        )

    def _get_device(
        self,
        device_type: str = None,
        cuda_number: int = 0
    ):
        """Get Default device for Torch and transformers.

        """
        import torch
        dev = torch.device("cpu")
        pipe_dev = -1
        dtype = torch.float32
        if device_type == 'cpu':
            pipe_dev = torch.device('cpu')
        if CUDA_DEFAULT_DEVICE == 'cpu':
            # Use CPU forced
            pipe_dev = torch.device('cpu')
        if torch.cuda.is_available():
            dev = torch.device("cuda")
            pipe_dev = 0  # first GPU
            # prefer bf16 if supported; else fp16
            if torch.cuda.is_bf16_supported():
                dtype = torch.bfloat16
            else:
                dtype = torch.float16
            pipe_dev = torch.device(f'cuda:{cuda_number}')
        if device_type == 'cuda':
            if torch.cuda.is_bf16_supported():
                dtype = torch.bfloat16
            else:
                dtype = torch.float16
            pipe_dev = torch.device(f'cuda:{cuda_number}')
        if torch.backends.mps.is_available():
            # Use CUDA Multi-Processing Service if available
            dev = torch.device("mps")
            pipe_dev = torch.device("mps")
            dtype = torch.float32  # fp16 on MPS is still flaky
        else:
            pipe_dev = torch.device(EMBEDDING_DEVICE)
        return pipe_dev, dev, dtype

    def get_embedding_dimension(self) -> int:
        return self._dimension

    async def initialize_model(self):
        """Async model initialization with GPU optimization"""
        async with self._model_lock:
            if self.model is None:
                loop = asyncio.get_event_loop()
                self.model = await loop.run_in_executor(
                    self.executor,
                    self._create_embedding
                )


    @abstractmethod
    def _create_embedding(self, model_name: str, **kwargs) -> Any:
        """
        Loads and returns the embedding model instance.
        """
        pass

    def embed_documents(
        self,
        texts: List[str],
        batch_size: Optional[int] = None
    ) -> List[List[float]]:
        """
        Generates embeddings for a list of documents.

        Args:
            texts: A list of document strings.

        Returns:
            A list of embedding vectors.
        """
        return self.model.encode(texts, convert_to_tensor=False).tolist()

    def embed_query(
        self,
        text: str,
        as_nparray: bool = False
    ) -> Union[List[float], List[np.ndarray]]:
        """
        Generates an embedding for a single query string.

        Args:
            text: The query string.

        Returns:
            The embedding vector for the query.
        """
        embeddings = self.model.encode(
            text,
            convert_to_tensor=False,
            normalize_embeddings=True,
            show_progress_bar=False
        )
        if as_nparray:
            return np.vstack(embeddings)
        return embeddings.tolist()

    def free(self):
        """
        Frees up resources used by the model.
        """
        import torch
        self.model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    @abstractmethod
    async def encode(self, texts: List[str], **kwargs) -> np.ndarray:
        pass
