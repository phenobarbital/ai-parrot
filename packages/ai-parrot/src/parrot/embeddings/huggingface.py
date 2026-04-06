from __future__ import annotations
from typing import List, Any, TYPE_CHECKING
from enum import Enum
import logging
import numpy as np
from parrot._imports import lazy_import
from .base import EmbeddingModel
from ..conf import HUGGINGFACE_EMBEDDING_CACHE_DIR


class ModelType(Enum):
    """Enumerator for different model types used in embeddings."""
    MPNET = "sentence-transformers/all-mpnet-base-v2"
    MINILM = "sentence-transformers/all-MiniLM-L6-v2"
    BGE_LARGE = "BAAI/bge-large-en-v1.5"
    GTE_BASE = "thenlper/gte-base"


class SentenceTransformerModel(EmbeddingModel):
    """
    A wrapper class for HuggingFace sentence-transformers embeddings.
    """
    model_name: str = "sentence-transformers/all-mpnet-base-v2"

    def __init__(self, model_name: str, **kwargs):
        """
        Initializes the embedding model with the specified model name.

        Args:
            model_name: The name of the Hugging Face model to load.
            **kwargs: Additional keyword arguments for SentenceTransformer.
        """
        super().__init__(model_name=model_name, **kwargs)
        self.logger.info(
            f"Initialized SentenceTransformerModel with model: {self.model_name}"
        )

    def _create_embedding(self, model_name: str = None, **kwargs) -> Any:
        """
        Creates and returns the SentenceTransformer model instance.

        Args:
            model_name: The name of the Hugging Face model to load.

        Returns:
            An instance of SentenceTransformer.
        """
        _st = lazy_import("sentence_transformers", package_name="sentence-transformers", extra="embeddings")
        SentenceTransformer = _st.SentenceTransformer
        import torch
        
        # Access self.device via property (calls _get_device lazily)
        device = self.device
        model_name = model_name or self.model_name
        
        self.logger.info(
            f"Loading embedding model '{model_name}' on device '{device}'"
        )
        
        # Suppress the "position_ids UNEXPECTED" load report from
        # sentence-transformers 5.x — the saved checkpoint still ships
        # a position_ids buffer that newer transformers removed from
        # MPNetModel.  It is harmless.
        st_logger = logging.getLogger("sentence_transformers.SentenceTransformer")
        prev_level = st_logger.level
        st_logger.setLevel(logging.WARNING)
        try:
            model = SentenceTransformer(
                model_name,
                device=device,
                cache_folder=HUGGINGFACE_EMBEDDING_CACHE_DIR
            )
        finally:
            st_logger.setLevel(prev_level)
        
        # Set dimension after loading model
        self._dimension = model.get_sentence_embedding_dimension()
        
        # Production optimizations
        model.eval()
        if str(device) == "cuda":
            model.half()  # Use FP16 for GPU inference
            torch.backends.cudnn.benchmark = True

        return model

    async def encode(self, texts: List[str], **kwargs) -> np.ndarray:
        import asyncio
        # Resolve model on the main thread (triggers lazy load if needed)
        # so the executor thread never calls _create_embedding.
        raw_model = self.model
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            lambda: raw_model.encode(texts, **kwargs)
        )
