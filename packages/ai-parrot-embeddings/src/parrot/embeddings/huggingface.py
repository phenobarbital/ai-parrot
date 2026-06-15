from __future__ import annotations
from typing import List, Any, Optional, Tuple
from enum import Enum
import logging
import numpy as np
from parrot._imports import lazy_import
from .base import EmbeddingModel
from ..conf import HUGGINGFACE_EMBEDDING_CACHE_DIR
from .catalog import EMBEDDING_MODELS
from .matryoshka import MatryoshkaConfig, validate_against_catalog

logger = logging.getLogger(__name__)

# HuggingFace models that ship custom modeling code in their repo and
# therefore require ``trust_remote_code=True`` to load via SentenceTransformer.
# Mirrors the pattern in parrot/rerankers/local.py:46.
_TRUST_REMOTE_CODE_MODELS: set[str] = {
    "nomic-ai/nomic-embed-text-v1.5",
    "jinaai/jina-embeddings-v3",
}

# Built once at import time from the catalog — O(1) lookup at runtime.
# Keys are lowercased model identifiers; values are (prefix_query, prefix_passage).
# The catalog's Pydantic validator guarantees the pair is consistent with
# requires_prefix, so the result here is correct by construction.
_PREFIX_LOOKUP: dict[str, tuple[str | None, str | None]] = {
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
        model_name: Model identifier (HuggingFace, OpenAI, or Google).

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
    """A wrapper class for HuggingFace sentence-transformers embeddings.

    Supports optional Matryoshka Representation Learning (MRL) truncation via
    the ``matryoshka`` kwarg.  When enabled, ``embed_documents`` and
    ``embed_query`` slice the native-dim output to the requested dimension and
    re-apply L2 normalisation so cosine similarity remains correct in the
    lower-dimensional space.  ``get_embedding_dimension()`` then reports the
    truncated dimension, so downstream consumers (pgvector table creation) see
    the correct size.

    The truncation is implemented with a plain numpy slice + renorm — we do NOT
    rely on ``SentenceTransformer.encode(truncate_dim=N)`` because that
    parameter is only available in newer sentence-transformers versions and the
    project does not pin to those.

    FEAT-237: Added ``backend`` and ``file_name`` kwargs for ONNX/OpenVINO
    CPU-optimised inference via ``sentence-transformers>=5.0.0``.
    """

    model_name: str = "sentence-transformers/all-mpnet-base-v2"

    def __init__(
        self,
        model_name: str,
        matryoshka: Optional[dict] = None,
        backend: Optional[str] = None,
        file_name: Optional[str] = None,
        **kwargs,
    ):
        """Initializes the embedding model with the specified model name.

        Args:
            model_name: The name of the Hugging Face model to load.
            matryoshka: Optional Matryoshka truncation config dict with shape
                ``{"enabled": bool, "dimension": int}``.  When ``None`` or
                ``{}`` the model behaves exactly as before FEAT-150.
            backend: Optional inference backend for CPU-optimised inference.
                One of ``"torch"`` (default), ``"onnx"``, or ``"openvino"``.
                Requires ``sentence-transformers>=5.0.0`` and the corresponding
                optional runtime (``optimum[onnxruntime]`` or ``openvino``).
                When ``None``, defaults to standard torch behaviour.
            file_name: Optional quantized model filename within the model repo,
                e.g. ``"model_quantized.onnx"`` for ONNX int8 quantized models.
                Forwarded to ``SentenceTransformer`` via ``model_kwargs``.
                Only used when ``backend`` is set; has no effect otherwise.
            **kwargs: Additional keyword arguments forwarded to the parent
                ``EmbeddingModel.__init__`` and ultimately to
                ``SentenceTransformer``.

        Raises:
            ConfigError: When ``matryoshka.enabled`` is ``True`` but the model
                is not in the catalog, has no ``matryoshka_dimensions``, or the
                requested dimension is not in the allowed list.
        """
        # FEAT-237: Store backend/file_name BEFORE super().__init__ so that
        # _create_embedding (called lazily on first .model access) picks them up.
        self._backend: Optional[str] = backend
        self._file_name: Optional[str] = file_name
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

        # FEAT-150: Matryoshka truncation support.
        # Validate the config up-front so any misconfiguration is caught at
        # construction time, not at the first embedding call.
        if matryoshka and isinstance(matryoshka, dict):
            _cfg = MatryoshkaConfig(**matryoshka)
        else:
            _cfg = MatryoshkaConfig()  # defaults: enabled=False, dimension=None

        validate_against_catalog(_cfg, self.model_name)

        # Store the truncated dim (None when disabled).  The hot path only
        # pays one boolean check per batch.
        self._matryoshka_dim: Optional[int] = (
            _cfg.dimension if _cfg.enabled else None
        )

        if self._matryoshka_dim is not None:
            self.logger.info(
                "Matryoshka truncation active for %s — effective dimension: %d",
                self.model_name,
                self._matryoshka_dim,
            )

        self.logger.info(
            "Initialized SentenceTransformerModel with model: %s", self.model_name
        )

    @property
    def model(self):
        """Return the raw SentenceTransformer model, syncing dimension on load.

        Extends the base ``model`` property to ensure ``self._dimension`` is
        populated after the lazy load.  The base property sets ``_dimension``
        only on the registry-cached wrapper, not on the calling instance.
        This override propagates the effective dimension (honoring the
        Matryoshka override) to ``self`` so that
        :meth:`get_embedding_dimension` returns the correct value.
        """
        raw = super().model
        if self._dimension is None and raw is not None and hasattr(raw, "get_embedding_dimension"):
            # Sync native dim from the raw model.
            self._dimension = raw.get_embedding_dimension()
            # Apply Matryoshka override if active.
            if self._matryoshka_dim is not None:
                self._dimension = self._matryoshka_dim
        return raw

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

    def _apply_matryoshka(
        self,
        vectors: "np.ndarray | list",
    ) -> "np.ndarray | list":
        """Slice and L2-renormalize vectors to the Matryoshka dimension.

        This is a no-op when Matryoshka truncation is disabled
        (``self._matryoshka_dim is None``).

        The truncation is a plain numpy slice followed by L2 renormalisation.
        We do NOT rely on ``SentenceTransformer.encode(truncate_dim=N)``
        because that parameter is only available in newer sentence-transformers
        versions; doing it ourselves keeps behaviour stable across versions.

        A truncated unit vector is no longer unit-norm (only the full vector
        was unit-norm). Re-normalising is required so cosine similarity stays
        comparable across dimensions.

        Args:
            vectors: Output of :meth:`encode` — either a numpy array of shape
                ``(n, native_dim)`` or a list of lists (when ``.tolist()`` was
                already called on the numpy result).

        Returns:
            Truncated and L2-renormalised vectors in the same container type
            as the input (numpy array → numpy array; list → list).
        """
        if self._matryoshka_dim is None:
            return vectors

        is_list = isinstance(vectors, list)
        arr = np.asarray(vectors, dtype=np.float32)
        sliced = arr[..., : self._matryoshka_dim]
        norms = np.linalg.norm(sliced, axis=-1, keepdims=True)
        # Avoid divide-by-zero: a zero vector remains zero (rare edge case
        # but possible for empty or all-pad inputs).
        norms = np.where(norms == 0, 1.0, norms)
        normalized = sliced / norms
        return normalized.tolist() if is_list else normalized

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

        When Matryoshka truncation is active (``self._matryoshka_dim`` is
        set), the native-dim vectors are sliced to the requested dimension
        and L2-renormalised before being returned.
        """
        prefixed = self._apply_passage_prefix(texts)
        result = await self.encode(prefixed, normalize_embeddings=True)
        # Apply Matryoshka truncation before the optional tolist() so we
        # can work on the numpy array when available (avoids a round-trip).
        result = self._apply_matryoshka(result)
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

        When Matryoshka truncation is active, the result is sliced and
        renormalised before ``embedding = result[0]`` is extracted.
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
        # Apply Matryoshka truncation on the list-of-lists before extracting
        # the single embedding so the helper operates on the right shape.
        result = self._apply_matryoshka(result)
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
            "Loading embedding model '%s' on device '%s'", model_name, device
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
        st_kwargs: dict[str, Any] = {
            "device": device,
            "cache_folder": HUGGINGFACE_EMBEDDING_CACHE_DIR,
        }
        if model_name in _TRUST_REMOTE_CODE_MODELS:
            st_kwargs["trust_remote_code"] = True
        # FEAT-237: Forward backend and file_name to SentenceTransformer
        # when explicitly set. backend selects the inference runtime
        # (torch/onnx/openvino); file_name selects a specific quantized
        # checkpoint file within the HuggingFace model repo.
        if self._backend is not None:
            st_kwargs["backend"] = self._backend
        if self._file_name is not None:
            # sentence-transformers passes file-level kwargs via model_kwargs.
            st_kwargs["model_kwargs"] = {"file_name": self._file_name}
        try:
            model = SentenceTransformer(model_name, **st_kwargs)
        finally:
            st_logger.setLevel(prev_level)
        
        # Set dimension after loading model.
        self._dimension = model.get_embedding_dimension()
        # FEAT-150: when Matryoshka truncation is active, override _dimension
        # to the truncated value so that downstream consumers (pgvector column
        # creation, AbstractStore dimension checks) see the effective size.
        if self._matryoshka_dim is not None:
            self._dimension = self._matryoshka_dim

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
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.executor,
            lambda: raw_model.encode(texts, **kwargs)
        )
