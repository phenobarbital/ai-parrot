"""UForm Embedding Provider.

Implements the ``UFormEmbedding`` concrete class using UForm's CLIP-style
encoders. Supports both PyTorch and ONNX backends for dev/GPU vs Knative
serving footprints respectively.

UForm returns text and image embeddings in the same shared vector space,
enabling cross-modal retrieval (text<->image) in PgVector.

External dependency: ``uform>=3.1`` (install with ``uform[torch]`` for GPU).
"""
from __future__ import annotations

import asyncio
from typing import Any, List, Optional, TYPE_CHECKING

import numpy as np

from parrot.embeddings.multimodal.base import (
    EmbeddingBackend,
    EmbeddingResult,
    ImageInput,
    MultimodalEmbedding,
    QuantizationMode,
    resolve_image,
)

if TYPE_CHECKING:
    pass


class UFormEmbedding(MultimodalEmbedding):
    """UForm-backed multimodal embedding provider.

    Wraps UForm's CLIP-style text and image encoders with dual backend
    support:
    - ``torch``: Full PyTorch model (~206 MB for multilingual-base).
      Preferred for dev and GPU inference.
    - ``onnx``: ONNX Runtime session (~100-300 MB). Preferred for Knative
      CPU serving with low memory footprint.

    Both backends produce embeddings in the same shared vector space for a
    given model, enabling cross-modal retrieval. All outputs are
    L2-normalized via :meth:`_postprocess`.

    Args:
        model_name: HuggingFace model identifier. Defaults to the
            multilingual-base model which supports 21 languages.
        backend: Runtime backend (torch or ONNX). Default: torch.
        output_dim: Matryoshka truncation dimension. ``None`` = full model dim.
        quantization: Post-processing quantization mode. Default: F32.
        device: Device string passed to UForm (``"cpu"`` or ``"cuda"``).
        **kwargs: Extra keyword arguments forwarded to :class:`EmbeddingModel`.
    """

    DEFAULT_MODEL = "unum-cloud/uform3-image-text-multilingual-base"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        backend: EmbeddingBackend = EmbeddingBackend.TORCH,
        output_dim: Optional[int] = None,
        quantization: QuantizationMode = QuantizationMode.F32,
        device: str = "cpu",
        **kwargs,
    ) -> None:
        super().__init__(model_name, output_dim=output_dim, quantization=quantization, **kwargs)
        self._backend = backend
        self._device = device
        # Set by _create_embedding; keyed by uform.Modality
        self._processors: dict = {}
        self._models: dict = {}

    # ------------------------------------------------------------------
    # Registry model type override
    # ------------------------------------------------------------------

    def _get_model_type(self) -> str:
        return "multimodal"

    # ------------------------------------------------------------------
    # EmbeddingModel interface
    # ------------------------------------------------------------------

    def _create_embedding(self, model_name: str, **kwargs) -> Any:
        """Load UForm model (torch or ONNX backend).

        Called by :meth:`initialize_model` inside a thread-pool executor so
        the event loop is not blocked during model download + load.

        Args:
            model_name: HuggingFace model identifier.
            **kwargs: Ignored (present for interface compatibility).

        Returns:
            A sentinel object (``True``) — the real models are stored on
            ``self._processors`` / ``self._models`` as side effects.

        Raises:
            ImportError: If ``uform`` is not installed.
            RuntimeError: If the ONNX backend is requested but
                ``onnxruntime`` is not available.
        """
        try:
            import uform
        except ImportError as exc:
            raise ImportError(
                "The 'uform' package is required for UFormEmbedding. "
                "Install it with: uv add 'uform>=3.1'"
            ) from exc

        backend_str = self._backend.value  # "torch" or "onnx"

        if backend_str == "onnx":
            try:
                import onnxruntime  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "onnxruntime is required for the ONNX backend. "
                    "Install it with: uv add onnxruntime"
                ) from exc

        processors, models = uform.get_model(
            model_name,
            backend=backend_str,
            device=self._device,
        )

        self._processors = processors
        self._models = models

        # Derive embedding dimension from the text encoder
        text_model = models.get(uform.Modality.TEXT_ENCODER)
        if text_model is not None:
            if hasattr(text_model, "embedding_dim"):
                self._dimension = text_model.embedding_dim
            elif hasattr(text_model, "text_encoder_session"):
                # ONNX path: get output shape from session metadata
                session = text_model.text_encoder_session
                output_info = session.get_outputs()
                if output_info:
                    self._dimension = output_info[-1].shape[-1]

        # Return a truthy sentinel so EmbeddingModel._model is set
        return True

    async def initialize_model(self) -> None:
        """Async model initialization — loads UForm in a thread executor.

        Overrides :meth:`EmbeddingModel.initialize_model` to ensure
        the UForm-specific _processors and _models are populated before
        use, not just _model.
        """
        async with self._model_lock:
            if not self._processors:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    self.executor,
                    lambda: self._create_embedding(self.model_name),
                )

    async def encode(self, texts: List[str], **kwargs) -> np.ndarray:
        """Encode a batch of texts to embeddings (async, non-blocking).

        Dispatches synchronous inference to the thread-pool executor so the
        event loop is never blocked.

        Args:
            texts: List of text strings to encode.
            **kwargs: Ignored.

        Returns:
            Embedding array of shape (N, D) as float32.
        """
        if not self._processors:
            await self.initialize_model()

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.executor,
            lambda: self._encode_text_sync(texts),
        )

    # ------------------------------------------------------------------
    # Sync encoding helpers (called inside executor — no async allowed)
    # ------------------------------------------------------------------

    def _encode_text_sync(self, texts: List[str]) -> np.ndarray:
        """Synchronous text encoding.  Must run in a thread executor.

        Args:
            texts: List of text strings.

        Returns:
            Float32 array of shape (N, D).
        """
        import uform

        text_processor = self._processors[uform.Modality.TEXT_ENCODER]
        text_model = self._models[uform.Modality.TEXT_ENCODER]

        processed = text_processor(texts)
        embeddings = text_model.encode(processed, return_features=False)

        # Convert tensor/ndarray to numpy float32
        return self._to_numpy(embeddings)

    def _encode_images_sync(self, pil_images: list) -> np.ndarray:
        """Synchronous image encoding.  Must run in a thread executor.

        Args:
            pil_images: List of PIL.Image.Image objects.

        Returns:
            Float32 array of shape (N, D).
        """
        import uform

        image_processor = self._processors[uform.Modality.IMAGE_ENCODER]
        image_model = self._models[uform.Modality.IMAGE_ENCODER]

        processed = image_processor(pil_images)
        embeddings = image_model.encode(processed, return_features=False)

        return self._to_numpy(embeddings)

    @staticmethod
    def _to_numpy(tensor_or_array) -> np.ndarray:
        """Convert a torch.Tensor or numpy array to float32 numpy.

        Args:
            tensor_or_array: A torch.Tensor, numpy array, or similar.

        Returns:
            Float32 numpy array.
        """
        if hasattr(tensor_or_array, "detach"):
            # torch.Tensor
            return tensor_or_array.detach().cpu().numpy().astype(np.float32)
        elif isinstance(tensor_or_array, np.ndarray):
            return tensor_or_array.astype(np.float32)
        else:
            return np.array(tensor_or_array, dtype=np.float32)

    # ------------------------------------------------------------------
    # MultimodalEmbedding abstract methods
    # ------------------------------------------------------------------

    async def embed_text(self, texts: List[str]) -> EmbeddingResult:
        """Embed a batch of text strings.

        Args:
            texts: List of text strings to embed.

        Returns:
            EmbeddingResult with modality="text" and L2-normalized embeddings.
        """
        if not self._processors:
            await self.initialize_model()

        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(
            self.executor,
            lambda: self._encode_text_sync(texts),
        )
        processed = self._postprocess(raw)
        return EmbeddingResult(
            embeddings=processed,
            dimension=processed.shape[-1],
            quantization=self._quantization,
            modality="text",
        )

    async def embed_images(self, images: List[ImageInput]) -> EmbeddingResult:
        """Embed a batch of images.

        Resolves all ImageInput values via :func:`resolve_image` before
        dispatching synchronous encoding to the thread executor.

        Args:
            images: List of image inputs (PIL.Image, bytes, or file paths).

        Returns:
            EmbeddingResult with modality="image" and L2-normalized embeddings.
        """
        if not self._processors:
            await self.initialize_model()

        # Resolve all images upfront — never in the encode hot path
        pil_images = [resolve_image(img) for img in images]

        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(
            self.executor,
            lambda: self._encode_images_sync(pil_images),
        )
        processed = self._postprocess(raw)
        return EmbeddingResult(
            embeddings=processed,
            dimension=processed.shape[-1],
            quantization=self._quantization,
            modality="image",
        )

    # ------------------------------------------------------------------
    # Resource management
    # ------------------------------------------------------------------

    def free(self) -> None:
        """Release model resources and clear caches."""
        self._processors = {}
        self._models = {}
        self._model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        self.logger.info("UFormEmbedding '%s' freed.", self.model_name)
