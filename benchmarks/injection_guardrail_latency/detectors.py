"""The tiers under test, behind one uniform detector protocol.

Every tier answers the same question — "how injection-like is this text,
in ``[0, 1]``?" — so latency, memory, and quality are measured the same
way for all of them:

``regex``
    The engine AI-Parrot ships today
    (``parrot.security.prompt_injection.PromptInjectionDetector``),
    including the framework-allowlist pre-strip the guardrail applies.
``embed-cosine``
    Proposed middle tier: encode the prompt once, take the maximum cosine
    against a seed catalogue of attack prompts. One encode per call, no
    classifier.
``clf-torch`` / ``clf-onnx`` / ``clf-onnx-int8``
    The transformer classifier AI-Parrot uses today via ``pytector``
    (``protectai/deberta-v3-base-prompt-injection``), under PyTorch and
    under ONNX Runtime with and without dynamic int8 quantization.

ONNX Runtime's thread pools are capped the same way
``voice/tts/supertonic_inference.py`` caps them: an uncapped intra-op pool
is sized to every physical core *per session*, which is what makes an
"off-loop" model still starve the event loop.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import ClassVar, Protocol, runtime_checkable

import numpy as np

logger = logging.getLogger(__name__)

#: The classifier AI-Parrot resolves today through ``pytector``'s
#: ``"deberta"`` alias — see ``pytector/detector.py`` ``predefined_models``.
DEFAULT_CLASSIFIER: str = "protectai/deberta-v3-base-prompt-injection"

#: Default embedding model for the cosine tier. Multilingual on purpose —
#: the corpus is EN/ES and a monolingual MiniLM scores Spanish paraphrases
#: near-randomly.
DEFAULT_EMBEDDER: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

#: Max sequence length for the classifier. Matches the truncation a
#: guardrail would apply on the hot path.
MAX_LENGTH: int = 256


@runtime_checkable
class Detector(Protocol):
    """Uniform contract for a benchmarked tier."""

    name: str

    def load(self) -> None:
        """Load whatever the tier needs. Called once, timed separately."""

    def score(self, text: str) -> float:
        """Return an injection-likeness score in ``[0, 1]`` for *text*."""


# ---------------------------------------------------------------------------
# Tier 0 — regex
# ---------------------------------------------------------------------------


class RegexDetector:
    """AI-Parrot's current stdlib regex engine.

    Threat levels are projected onto ``[0, 1]`` so the tier can share the
    threshold-sweep machinery: CRITICAL -> 1.0, HIGH -> 0.9, MEDIUM -> 0.6,
    LOW -> 0.3, no threat -> 0.0.
    """

    name = "regex"

    _LEVEL_SCORES: ClassVar[dict[str, float]] = {
        "critical": 1.0, "high": 0.9, "medium": 0.6, "low": 0.3,
    }

    def __init__(self) -> None:
        self._detector = None

    def load(self) -> None:
        from parrot.security.prompt_injection import PromptInjectionDetector

        self._detector = PromptInjectionDetector(logger=logger)

    def score(self, text: str) -> float:
        # Mirrors PromptInjectionGuardrail.check(): scan the text with
        # framework-injected metadata stripped, never the raw wrapper.
        scan_text = self._detector.strip_framework_patterns(text)
        _, threats = self._detector.sanitize(scan_text, strict=True)
        if not threats:
            return 0.0
        best = 0.0
        for threat in threats:
            level = threat.get("level")
            key = getattr(level, "value", str(level)).lower()
            best = max(best, self._LEVEL_SCORES.get(key, 0.3))
        return best


# ---------------------------------------------------------------------------
# Tier 1 — embedding similarity
# ---------------------------------------------------------------------------


class EmbedCosineDetector:
    """Maximum cosine similarity against a seed catalogue of attacks.

    The catalogue is embedded once at load time; each call costs exactly
    one encode plus an ``(1, d) @ (d, N)`` matmul over a catalogue of a few
    hundred rows — negligible next to the encode.
    """

    def __init__(
        self,
        seed_corpus: list[str],
        model_name: str = DEFAULT_EMBEDDER,
        backend: str = "torch",
    ) -> None:
        self.name = f"embed-cosine-{backend}"
        self.model_name = model_name
        self.backend = backend
        self._seed_corpus = seed_corpus
        self._model = None
        self._seed_matrix: np.ndarray | None = None

    def load(self) -> None:
        self._model = _load_sentence_encoder(self.model_name, self.backend)
        matrix = np.asarray(
            self._model.encode(self._seed_corpus, convert_to_numpy=True),
            dtype=np.float32,
        )
        self._seed_matrix = _l2_normalise(matrix)

    def score(self, text: str) -> float:
        vector = np.asarray(
            self._model.encode([text], convert_to_numpy=True), dtype=np.float32
        )
        vector = _l2_normalise(vector)
        sims = vector @ self._seed_matrix.T
        # Cosine is in [-1, 1]; clamp the negative half to 0 so the score
        # shares the [0, 1] range every other tier reports.
        return float(max(0.0, sims.max()))


def _l2_normalise(matrix: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalisation with a zero-norm guard."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-9)


def _load_sentence_encoder(model_name: str, backend: str):
    """Load a sentence encoder, preferring AI-Parrot's embeddings registry.

    Args:
        model_name: HuggingFace-style model id.
        backend: ``"torch"`` or ``"onnx"`` (FEAT-237 ``backend`` kwarg).

    Returns:
        An object exposing ``encode(texts, convert_to_numpy=True)``.
    """
    try:
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance()
        wrapper = registry.get_or_create_sync(
            model_name, model_type="huggingface", backend=backend
        )
        model = getattr(wrapper, "model", wrapper)
        if hasattr(model, "encode"):
            return model
        logger.warning("Registry wrapper has no .encode(); falling back")
    except Exception as exc:  # noqa: BLE001 - benchmark fallback path
        logger.warning("EmbeddingRegistry unavailable (%s); using sentence-transformers", exc)

    from sentence_transformers import SentenceTransformer

    kwargs = {"backend": backend} if backend != "torch" else {}
    return SentenceTransformer(model_name, device="cpu", **kwargs)


# ---------------------------------------------------------------------------
# Tier 2 — transformer classifier
# ---------------------------------------------------------------------------


class TransformerDetector:
    """The deBERTa prompt-injection classifier under torch or ONNX Runtime.

    Args:
        model_id: HuggingFace model id (for torch) — also the tokenizer
            source for the ONNX backends.
        backend: ``"torch"``, ``"onnx"``, or ``"onnx-int8"``.
        onnx_dir: Directory holding the exported graph. Required for the
            ONNX backends; produced by
            :mod:`benchmarks.injection_guardrail_latency.export`.
        intra_op_threads: ORT intra-op cap. ``0`` leaves the ORT default
            (every physical core, per session) — deliberately available so
            the benchmark can *show* what the uncapped pool costs.
        inter_op_threads: ORT inter-op cap.
    """

    def __init__(
        self,
        model_id: str = DEFAULT_CLASSIFIER,
        backend: str = "torch",
        onnx_dir: Path | None = None,
        intra_op_threads: int = 2,
        inter_op_threads: int = 1,
    ) -> None:
        self.name = f"clf-{backend}"
        self.model_id = model_id
        self.backend = backend
        self.onnx_dir = onnx_dir
        self.intra_op_threads = intra_op_threads
        self.inter_op_threads = inter_op_threads
        self._tokenizer = None
        self._model = None
        self._session = None
        self._injection_index = 1

    def load(self) -> None:
        from transformers import AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        if self.backend == "torch":
            self._load_torch()
        else:
            self._load_onnx()

    def _load_torch(self) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification

        torch.set_num_threads(max(1, self.intra_op_threads))
        model = AutoModelForSequenceClassification.from_pretrained(self.model_id)
        model.eval()
        self._model = model
        self._injection_index = _resolve_injection_index(model.config.id2label)

    def _load_onnx(self) -> None:
        import json

        import onnxruntime as ort

        if self.onnx_dir is None or not self.onnx_dir.exists():
            raise FileNotFoundError(
                f"ONNX graph directory not found: {self.onnx_dir}. Export it first:\n"
                f"  python -m benchmarks.injection_guardrail_latency.export "
                f"--model {self.model_id} --output-dir <dir>"
            )
        graph_name = "model_int8.onnx" if self.backend == "onnx-int8" else "model.onnx"
        graph_path = self.onnx_dir / graph_name
        if not graph_path.exists():
            raise FileNotFoundError(f"ONNX graph not found: {graph_path}")

        opts = ort.SessionOptions()
        # Cap ORT's CPU parallelism. Uncapped, the intra-op pool is sized to
        # every physical core PER SESSION — the failure mode documented in
        # voice/tts/supertonic_inference.py:462-472, where it pegged all cores
        # and froze the aiohttp event loop.
        if self.intra_op_threads > 0:
            opts.intra_op_num_threads = self.intra_op_threads
        if self.inter_op_threads > 0:
            opts.inter_op_num_threads = self.inter_op_threads
        self._session = ort.InferenceSession(
            str(graph_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self._input_names = {inp.name for inp in self._session.get_inputs()}

        config_path = self.onnx_dir / "config.json"
        if config_path.exists():
            id2label = json.loads(config_path.read_text()).get("id2label", {})
            self._injection_index = _resolve_injection_index(id2label)

    def score(self, text: str) -> float:
        if self.backend == "torch":
            return self._score_torch(text)
        return self._score_onnx(text)

    def _score_torch(self, text: str) -> float:
        import torch

        inputs = self._tokenizer(
            text, return_tensors="pt", truncation=True, max_length=MAX_LENGTH
        )
        with torch.no_grad():
            logits = self._model(**inputs).logits
        probs = torch.softmax(logits, dim=-1)[0]
        return float(probs[self._injection_index].item())

    def _score_onnx(self, text: str) -> float:
        encoded = self._tokenizer(
            text, return_tensors="np", truncation=True, max_length=MAX_LENGTH
        )
        feed = {
            name: value
            for name, value in encoded.items()
            if name in self._input_names
        }
        logits = self._session.run(None, feed)[0]
        return float(_softmax(logits[0])[self._injection_index])


def _softmax(logits: np.ndarray) -> np.ndarray:
    """Numerically stable softmax over the last axis."""
    shifted = logits - np.max(logits)
    exps = np.exp(shifted)
    return exps / np.sum(exps)


def _resolve_injection_index(id2label: dict) -> int:
    """Locate the positive ("injection") class index from a label map.

    Args:
        id2label: The model config's ``id2label`` mapping. Keys may be
            ``int`` (torch config) or ``str`` (JSON round-trip).

    Returns:
        The index of the injection class, defaulting to ``1``.
    """
    for key, label in (id2label or {}).items():
        if "inject" in str(label).lower():
            return int(key)
    return 1


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def build_detector(
    tier: str,
    *,
    seed_corpus: list[str],
    classifier_id: str = DEFAULT_CLASSIFIER,
    embedder_id: str = DEFAULT_EMBEDDER,
    onnx_dir: Path | None = None,
    intra_op_threads: int = 2,
) -> Detector:
    """Construct (but do not load) the detector for *tier*.

    Args:
        tier: One of ``regex``, ``embed-cosine-torch``, ``embed-cosine-onnx``,
            ``clf-torch``, ``clf-onnx``, ``clf-onnx-int8``.
        seed_corpus: Attack catalogue for the cosine tier.
        classifier_id: HuggingFace id of the classifier under test.
        embedder_id: HuggingFace id of the sentence encoder.
        onnx_dir: Directory of exported ONNX graphs.
        intra_op_threads: ORT / torch thread cap.

    Returns:
        An unloaded :class:`Detector`.

    Raises:
        ValueError: If *tier* is unknown.
    """
    if tier == "regex":
        return RegexDetector()
    if tier.startswith("embed-cosine"):
        backend = "onnx" if tier.endswith("onnx") else "torch"
        return EmbedCosineDetector(seed_corpus, model_name=embedder_id, backend=backend)
    if tier.startswith("clf-"):
        return TransformerDetector(
            model_id=classifier_id,
            backend=tier.removeprefix("clf-"),
            onnx_dir=onnx_dir,
            intra_op_threads=intra_op_threads,
        )
    raise ValueError(f"Unknown tier: {tier!r}")


ALL_TIERS: list[str] = [
    "regex",
    "embed-cosine-torch",
    "clf-torch",
    "clf-onnx",
    "clf-onnx-int8",
]


def pin_thread_env(threads: int = 1) -> None:
    """Pin BLAS/OMP thread counts for reproducible numbers.

    Must run before numpy/torch import to take effect; the harness calls
    it at module import.
    """
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "BLIS_NUM_THREADS"):
        os.environ.setdefault(var, str(threads))
