"""Local cross-encoder reranker implementation.

This module provides ``LocalCrossEncoderReranker``, a production-grade
in-process reranker that loads a HuggingFace cross-encoder model once and
scores ``(query, passage)`` pairs via batched forward passes.

Supported models:

- ``BAAI/bge-reranker-v2-m3`` (default, 568M params, multilingual)
- ``jinaai/jina-reranker-v2-base-multilingual`` (278M, requires
  ``trust_remote_code=True``)
- ``cross-encoder/ms-marco-MiniLM-L-12-v2`` (33M, English-only, fast CI path)

Device/precision autodetection:

- GPU available → FP16 (``model.half()``)
- CPU only → INT8 (``torch.quantization.quantize_dynamic`` on ``nn.Linear``)
- Override via ``RerankerConfig.device`` / ``RerankerConfig.precision``

Raises:
    ImportError: At module import time if ``transformers`` or ``torch`` are
        not installed.
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import ClassVar, Optional

try:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
except ImportError as _import_err:
    raise ImportError(
        "LocalCrossEncoderReranker requires 'transformers' and 'torch'. "
        "Install them with:  uv add transformers torch"
    ) from _import_err

from parrot.rerankers.abstract import AbstractReranker
from parrot.rerankers.models import RerankedDocument, RerankerConfig
from parrot.stores.models import SearchResult

logger = logging.getLogger(__name__)

# Jina v2 models that require trust_remote_code=True
_JINA_MODELS = {"jinaai/jina-reranker-v2-base-multilingual"}


class LocalCrossEncoderReranker(AbstractReranker):
    """In-process cross-encoder reranker using HuggingFace models.

    Loads the model eagerly at construction time with optional warmup so that
    the first real ``rerank()`` call does not pay cold-start latency.

    A process-wide model cache (keyed by ``(model_name, device, precision)``)
    ensures that two bots configured with the same reranker share one model
    in memory.  A per-device ``ThreadPoolExecutor(max_workers=1)`` serialises
    GPU access to prevent OOM under concurrent requests.

    Example:
        >>> from parrot.rerankers import LocalCrossEncoderReranker, RerankerConfig
        >>> reranker = LocalCrossEncoderReranker(
        ...     config=RerankerConfig(
        ...         model_name="cross-encoder/ms-marco-MiniLM-L-12-v2",
        ...         device="cpu",
        ...         precision="fp32",
        ...     )
        ... )
        >>> results = await reranker.rerank("my query", documents, top_n=5)
    """

    # (model_name, device, precision) -> (model, tokenizer)
    _model_cache: ClassVar[dict] = {}
    # device_str -> ThreadPoolExecutor(max_workers=1)
    _executors: ClassVar[dict] = {}

    def __init__(
        self,
        config: Optional[RerankerConfig] = None,
        **kwargs,
    ) -> None:
        """Initialise the reranker, load the model, and optionally warm it up.

        Args:
            config: A ``RerankerConfig`` instance.  If ``None``, kwargs are
                used to build one (e.g. ``model_name="..."``, ``device="cpu"``).
            **kwargs: Forwarded to ``RerankerConfig`` when ``config`` is None.
        """
        self.logger = logging.getLogger(__name__)

        if config is None:
            config = RerankerConfig(**kwargs)
        self.config = config

        # Resolve device
        if config.device == "auto":
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self._device = config.device

        # Resolve precision
        if config.precision == "auto":
            self._precision = "fp16" if self._device.startswith("cuda") else "int8"
        else:
            self._precision = config.precision

        # Jina v2 guard
        model_name = config.model_name
        if model_name in _JINA_MODELS and not config.trust_remote_code:
            raise ValueError(
                f"Model '{model_name}' requires trust_remote_code=True. "
                "Set RerankerConfig(trust_remote_code=True) to load it."
            )

        # Load model (from cache or fresh)
        cache_key = (model_name, self._device, self._precision)
        if cache_key not in self._model_cache:
            self.logger.info(
                "Loading reranker model '%s' on %s/%s",
                model_name,
                self._device,
                self._precision,
            )
            tokenizer = AutoTokenizer.from_pretrained(
                model_name,
                trust_remote_code=config.trust_remote_code,
            )
            model = AutoModelForSequenceClassification.from_pretrained(
                model_name,
                trust_remote_code=config.trust_remote_code,
            )
            model.eval()

            # Apply precision
            if self._precision == "fp16":
                if not self._device.startswith("cuda"):
                    self.logger.warning(
                        "FP16 requested on CPU; falling back to FP32."
                    )
                    self._precision = "fp32"
                else:
                    model = model.half()
            elif self._precision == "int8":
                model = torch.quantization.quantize_dynamic(
                    model,
                    {torch.nn.Linear},
                    dtype=torch.qint8,
                )

            model = model.to(self._device)
            self._model_cache[cache_key] = (model, tokenizer)
            self.logger.info(
                "Reranker model '%s' loaded and cached (key=%s)",
                model_name,
                cache_key,
            )

        self._model, self._tokenizer = self._model_cache[cache_key]

        # Per-device executor (serialises GPU access)
        if self._device not in self._executors:
            self._executors[self._device] = ThreadPoolExecutor(max_workers=1)
        self._executor = self._executors[self._device]

        # Eager warmup
        if config.warmup:
            self._warmup()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def rerank(
        self,
        query: str,
        documents: list[SearchResult],
        top_n: Optional[int] = None,
    ) -> list[RerankedDocument]:
        """Score ``(query, document)`` pairs and return them sorted by relevance.

        Args:
            query: User query text.
            documents: Candidate documents from upstream retrieval.
            top_n: If set, return only the top N results.  ``None`` returns all.

        Returns:
            ``RerankedDocument`` list sorted by descending ``rerank_score``.
            On failure, returns the original ordering with ``rerank_score=NaN``.
        """
        if not documents:
            return []

        t0 = time.monotonic()
        loop = asyncio.get_event_loop()

        try:
            scores = await loop.run_in_executor(
                self._executor,
                self._rerank_sync,
                query,
                [doc.content for doc in documents],
            )
        except Exception as exc:
            self.logger.warning(
                "Reranker forward pass failed; returning original order. Error: %s",
                exc,
            )
            return self._fallback_result(documents, self.config.model_name)

        latency_ms = (time.monotonic() - t0) * 1000.0

        # Build RerankedDocument list, sorted descending
        scored = sorted(
            enumerate(zip(scores, documents)),
            key=lambda x: x[1][0],
            reverse=True,
        )

        results = [
            RerankedDocument(
                document=doc,
                rerank_score=float(score),
                rerank_rank=new_rank,
                original_rank=orig_rank,
                rerank_model=self.config.model_name,
                rerank_latency_ms=latency_ms,
            )
            for new_rank, (orig_rank, (score, doc)) in enumerate(scored)
        ]

        if top_n is not None:
            results = results[:top_n]

        return results

    async def cleanup(self) -> None:
        """Shut down the per-device ThreadPoolExecutor.

        Does NOT evict the model from the process cache — the model is shared
        across all instances that use the same ``(model_name, device, precision)``
        triple and should not be unloaded unilaterally.
        """
        executor = self._executors.pop(self._device, None)
        if executor is not None:
            executor.shutdown(wait=False)
            self.logger.debug("Executor for device '%s' shut down.", self._device)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rerank_sync(
        self,
        query: str,
        passages: list[str],
    ) -> list[float]:
        """Synchronous batched scoring (runs in the thread pool).

        Args:
            query: User query text.
            passages: Document texts to score.

        Returns:
            List of relevance scores aligned with ``passages``.
        """
        batch_size = self.config.batch_size
        max_length = self.config.max_length

        all_scores: list[float] = []

        # Chunk into mini-batches
        for start in range(0, len(passages), batch_size):
            batch_passages = passages[start : start + batch_size]
            pairs = [(query, p) for p in batch_passages]

            inputs = self._tokenizer(
                pairs,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            inputs = {k: v.to(self._device) for k, v in inputs.items()}

            with torch.inference_mode():
                logits = self._model(**inputs).logits.squeeze(-1)

            all_scores.extend(logits.float().cpu().tolist())

        return all_scores

    def _warmup(self) -> None:
        """Execute a dummy forward pass to trigger CUDA kernel JIT."""
        try:
            self._rerank_sync("warmup query", ["warmup passage"])
            self.logger.debug(
                "Reranker warmup complete for model '%s'.", self.config.model_name
            )
        except Exception as exc:
            self.logger.warning("Reranker warmup failed (non-fatal): %s", exc)

    @staticmethod
    def _fallback_result(
        documents: list[SearchResult],
        model_name: str,
    ) -> list[RerankedDocument]:
        """Return documents in original order with NaN scores.

        Args:
            documents: Original retrieval results.
            model_name: Model ID to populate on the fallback documents.

        Returns:
            ``RerankedDocument`` list preserving original order with NaN scores.
        """
        nan = float("nan")
        return [
            RerankedDocument(
                document=doc,
                rerank_score=nan,
                rerank_rank=i,
                original_rank=i,
                rerank_model=model_name,
            )
            for i, doc in enumerate(documents)
        ]
