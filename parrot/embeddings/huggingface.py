from typing import List, Any
from enum import Enum
import numpy as np
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
        self._dimension = self.model.get_sentence_embedding_dimension()

    def _create_embedding(self, model_name: str = None, **kwargs) -> Any:
        """
        Creates and returns a SentenceTransformer model instance.

        Args:
            model_name: The name of the Hugging Face model to load.

        Returns:
            An instance of SentenceTransformer.
        """
        from sentence_transformers import SentenceTransformer
        import torch
        device, _, _ = self._get_device()
        model_name = model_name or self.model_name
        self.logger.info(
            f"Loading embedding model '{model_name}' on device '{device}'"
        )
        model = SentenceTransformer(
            model_name,
            device=device,
            cache_folder=HUGGINGFACE_EMBEDDING_CACHE_DIR
        )
        # Production optimizations
        model.eval()
        if self.device == "cuda":
            model.half()  # Use FP16 for GPU inference
            torch.backends.cudnn.benchmark = True

        return model

    async def encode(self, texts: List[str], **kwargs) -> np.ndarray:
        return self.model.encode(texts, **kwargs)
