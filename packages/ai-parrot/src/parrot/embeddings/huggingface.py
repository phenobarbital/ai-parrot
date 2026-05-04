from __future__ import annotations
from typing import List, Any, Optional, Tuple, TYPE_CHECKING
from enum import Enum
import logging
import numpy as np
from parrot._imports import lazy_import
from .base import EmbeddingModel
from ..conf import HUGGINGFACE_EMBEDDING_CACHE_DIR
from .catalog import EMBEDDING_MODELS

logger = logging.getLogger(__name__)

# Built once at import time from the catalog — O(1) lookup at runtime.
# Keys are lowercased model identifiers; values are (prefix_query, prefix_passage).
# The catalog's Pydantic validator guarantees the pair is consistent with
# requires_prefix, so the result here is correct by construction.
_PREFIX_LOOKUP: dict[str, Tuple[Optional[str], Optional[str]]] = {
    entry["model"].lower(): (entry["prefix_query"], entry["prefix_passage"])
    for entry in EMBEDDING_MODELS
}


def _resolve_prefixes(model_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Return the (query_prefix, passage_prefix) pair for a model.

    Catalog-driven: looks up ``model_name`` (case-insensitive) in
    ``EMBEDDING_MODELS`` and returns the per-model prefix pair declared
    there. The catalog's Pydantic validator guarantees the pair is
    consistent with ``requires_prefix``, so the result here is correct
    by construction.

    Out-of-catalog models return ``(None, None)`` and emit one INFO log,
    preserving the silent-passthrough behaviour required for backward
    compatibility with operators using third-party models.

    Args:
        model_name: HuggingFace model identifier.

    Returns:
        Tuple ``(query_prefix, passage_prefix)``. Either entry may be
        ``None`` when no prefix is required on that side.
    """
    if not model_name:
        return (None, None)
    pair = _PREFIX_LOOKUP.get(model_name.lower())
    if pair is None:
        logger.info(
            "Model %s not in embedding catalog; encoding without prefix",
            model_name,
        )
        return (None, None)
    return pair


class ModelType(Enum):
    """Enumerator for different model types used in embeddings."""
    # General-purpose / Similarity
    MPNET = "sentence-transformers/all-mpnet-base-v2"
    MINILM = "sentence-transformers/all-MiniLM-L6-v2"
    MINILM_L12 = "sentence-transformers/all-MiniLM-L12-v2"
    # Information Retrieval
    GTE_SMALL = "thenlper/gte-small"
    GTE_BASE = "thenlper/gte-base"
    GTE_LARGE = "thenlper/gte-large"
    MSMARCO = "sentence-transformers/msmarco-MiniLM-L12-v3"
    MULTI_QA = "sentence-transformers/multi-qa-mpnet-base-dot-v1"
    MULTI_QA_COS = "sentence-transformers/multi-qa-mpnet-base-cos-v1"
    GTR_T5 = "sentence-transformers/gtr-t5-large"
    E5_BASE = "intfloat/e5-base-v2"
    E5_LARGE = "intfloat/e5-large-v2"
    # BGE family
    BGE_SMALL = "BAAI/bge-small-en-v1.5"
    BGE_BASE = "BAAI/bge-base-en-v1.5"
    BGE_LARGE = "BAAI/bge-large-en-v1.5"
    BGE_M3 = "BAAI/bge-m3"
    # Multilingual
    GTE_MULTI = "Alibaba-NLP/gte-multilingual-base"
    E5_MULTI_BASE = "intfloat/multilingual-e5-base"
    E5_MULTI_LARGE = "intfloat/multilingual-e5-large"
    PARA_MULTI_MINILM = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    PARA_MULTI_MPNET = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    # Code / Technical
    JINA_CODE = "jinaai/jina-embeddings-v2-base-code"
    JINA_EN = "jinaai/jina-embeddings-v2-base-en"
    JINA_V3 = "jinaai/jina-embeddings-v3"
    # Matryoshka / Flexible Dimensions
    NOMIC = "nomic-ai/nomic-embed-text-v1.5"
    MXBAI_LARGE = "mixedbread-ai/mxbai-embed-large-v1"
    # Gemma Embeddings
    EMBEDDING_GEMMA = "google/embeddinggemma-300m"
    # Snowflake Arctic
    ARCTIC_S = "Snowflake/snowflake-arctic-embed-s"
    ARCTIC_M = "Snowflake/snowflake-arctic-embed-m-v1.5"
    ARCTIC_L = "Snowflake/snowflake-arctic-embed-l"
    # Instruct-Tuned
    GTE_QWEN2_INSTRUCT = "Alibaba-NLP/gte-Qwen2-1.5B-instruct"
    E5_MISTRAL_INSTRUCT = "intfloat/e5-mistral-7b-instruct"
    # High-Dimension / Specialized
    NV_EMBED_V2 = "nvidia/NV-Embed-v2"


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
        # Resolve model-family prefixes once at construction so
        # embed_documents / embed_query stay hot-path cheap. See
        # _resolve_prefixes for the mapping rationale.
        self._query_prefix, self._passage_prefix = _resolve_prefixes(
            self.model_name
        )
        if self._query_prefix or self._passage_prefix:
            self.logger.info(
                "Using instruction prefixes for %s — query=%r passage=%r",
                self.model_name, self._query_prefix, self._passage_prefix,
            )
        self.logger.info(
            "Initialized SentenceTransformerModel with model: %s", self.model_name
        )

    def _apply_query_prefix(self, text: str) -> str:
        """Prepend the model-family query prefix (if any)."""
        if self._query_prefix:
            return f"{self._query_prefix}{text}"
        return text

    def _apply_passage_prefix(self, texts: List[str]) -> List[str]:
        """Prepend the model-family passage prefix (if any) to every text."""
        if self._passage_prefix:
            return [f"{self._passage_prefix}{t}" for t in texts]
        return texts

    async def embed_documents(
        self,
        texts: List[str],
        batch_size: Optional[int] = None,
    ) -> List[List[float]]:
        """Encode documents, applying the family-specific passage prefix.

        Overrides :meth:`EmbeddingModel.embed_documents` so that E5/BGE
        models receive the prefix they were trained on. Without this,
        retrieval quality collapses — similarity scores cluster near
        the centroid and ranking becomes essentially random.
        """
        prefixed = self._apply_passage_prefix(texts)
        result = await self.encode(prefixed, normalize_embeddings=True)
        if hasattr(result, "tolist"):
            return result.tolist()
        return result

    async def embed_query(
        self,
        text: str,
        as_nparray: bool = False,
    ) -> Any:
        """Encode a query, applying the family-specific query prefix.

        Overrides :meth:`EmbeddingModel.embed_query` for the same
        reason as :meth:`embed_documents` — E5 models in particular
        are trained with asymmetric ``query:`` / ``passage:`` markers
        and degrade badly when either side is omitted.
        """
        prefixed = self._apply_query_prefix(text)
        result = await self.encode(
            [prefixed],
            convert_to_tensor=False,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if hasattr(result, "tolist"):
            result = result.tolist()
        embedding = result[0]
        if as_nparray:
            return [np.array(embedding)]
        return embedding

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
        
        # Suppress noisy DEBUG output from HTTP transport used by
        # huggingface_hub when checking/downloading model files.
        for _noisy in ("httpcore", "httpx", "huggingface_hub.file_download"):
            logging.getLogger(_noisy).setLevel(logging.WARNING)

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
        self._dimension = model.get_embedding_dimension()
        
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
