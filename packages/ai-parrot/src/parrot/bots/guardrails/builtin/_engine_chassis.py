"""Shared ONNX scoring-engine chassis for ML guardrails (FEAT-761).

Stateless engine pieces factored out of ``prompt_injection.py`` plus a
generic, ``EngineSpec``-driven offline resolver and warm-up for guardrail
categories added after FEAT-439 (jailbreak). The prompt-injection
guardrail keeps its own stateful resolution chain (its tests patch it in
place); only its stateless engine/helpers delegate here.

Import discipline (FEAT-439): onnxruntime / transformers / huggingface_hub /
numpy are imported inside functions only — importing this module is free.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

DEFAULT_MAX_LENGTH = 512

_WARMUP_DUMMY_TEXT = "the quick brown fox jumps over the lazy dog"


@dataclass(frozen=True)
class EngineSpec:
    """Static description of one guardrail category's ML engine.

    Attributes:
        category: Memo key and log label (``"jailbreak"``).
        env_prefix: Prefix for ``<P>_ONNX_DIR`` / ``<P>_ONNX_MODEL`` /
            ``<P>_ONNX_GRAPH`` / ``<P>_ORT_INTRA_OP_THREADS`` /
            ``<P>_ORT_INTER_OP_THREADS``.
        default_model_id: HF repo id used when ``<P>_ONNX_MODEL`` is unset.
        known_graph_paths: repo id -> graph path inside the repo.
        kind: ``"classifier"`` (softmax over logits) or ``"embedding"``.
        positive_label_match: Substrings (lower-case) identifying the positive
            class in ``id2label``; first match wins, default index 1.
        max_length: Tokenizer truncation length.
        warmup_allow_patterns: Extra ``snapshot_download`` patterns besides
            the graph (tokenizer/config files).
    """

    category: str
    env_prefix: str
    default_model_id: str
    known_graph_paths: dict[str, str] = field(default_factory=dict)
    kind: Literal["classifier", "embedding"] = "classifier"
    positive_label_match: tuple[str, ...] = ("inject",)
    max_length: int = DEFAULT_MAX_LENGTH
    warmup_allow_patterns: tuple[str, ...] = (
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "*.model",
    )


@runtime_checkable
class ScoringEngine(Protocol):
    """Uniform engine contract: a probability in ``[0, 1]`` for *text*."""

    engine_name: str
    model_id: str

    def score(self, text: str) -> float:
        """Synchronous; callers on the event loop must offload it."""
        ...


def env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back to ``default``.

    A blank or unparseable value yields ``default`` rather than raising.

    Args:
        name: Environment variable name.
        default: Value returned when unset or invalid.

    Returns:
        The parsed integer, or ``default``.
    """
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def softmax(logits: Any) -> Any:
    """Numerically stable softmax over the last axis.

    Args:
        logits: A 1-D ``numpy.ndarray`` of raw logits.

    Returns:
        A ``numpy.ndarray`` of probabilities summing to 1.
    """
    import numpy as np

    shifted = logits - np.max(logits)
    exps = np.exp(shifted)
    return exps / np.sum(exps)


def load_tokenizer(tokenizer_dir: Path) -> Any:
    """Load the classifier tokenizer from a local directory, never downloading.

    Tries ``AutoTokenizer`` first; when it rejects the config but a
    ``tokenizer.json`` is present, falls back to ``PreTrainedTokenizerFast``
    with the special tokens declared in ``tokenizer_config.json``.

    Args:
        tokenizer_dir: Local directory holding the tokenizer files.

    Returns:
        A callable tokenizer accepting ``return_tensors="np"``.

    Raises:
        Exception: Whatever ``AutoTokenizer`` raised when no
            ``tokenizer.json`` fallback is available.
    """
    from transformers import AutoTokenizer

    try:
        return AutoTokenizer.from_pretrained(str(tokenizer_dir), local_files_only=True)
    except ValueError as exc:
        tokenizer_file = tokenizer_dir / "tokenizer.json"
        if not tokenizer_file.exists():
            raise
        logger.info(
            "AutoTokenizer rejected %s (%s); loading tokenizer.json directly " "via PreTrainedTokenizerFast.",
            tokenizer_dir,
            exc,
        )
        from transformers import PreTrainedTokenizerFast

        special: dict[str, Any] = {}
        config_file = tokenizer_dir / "tokenizer_config.json"
        if config_file.exists():
            try:
                cfg = json.loads(config_file.read_text())
            except (OSError, ValueError):
                cfg = {}
            for key in (
                "pad_token",
                "cls_token",
                "sep_token",
                "unk_token",
                "mask_token",
                "bos_token",
                "eos_token",
                "model_max_length",
            ):
                if key in cfg and not isinstance(cfg[key], dict):
                    special[key] = cfg[key]
        return PreTrainedTokenizerFast(tokenizer_file=str(tokenizer_file), **special)


def resolve_positive_index(tokenizer_dir: Path, positive_label_match: tuple[str, ...] = ("inject",)) -> int:
    """Index of the first ``id2label`` entry containing any of ``positive_label_match``.

    Generalizes ``prompt_injection._resolve_injection_index`` (same defaults,
    same warnings, same index-1 fallback).

    Args:
        tokenizer_dir: Directory containing ``config.json``.
        positive_label_match: Lower-case substrings identifying the positive class.

    Returns:
        The positive-class index, defaulting to ``1`` when the config is
        missing, unreadable, or has no matching label.
    """
    config_path = tokenizer_dir / "config.json"
    if not config_path.exists():
        logger.warning(
            "No config.json in %s; defaulting injection-class index to 1 " "(unverified).",
            tokenizer_dir,
        )
        return 1
    try:
        config = json.loads(config_path.read_text())
    except (OSError, ValueError) as exc:
        logger.warning(
            "Could not read id2label from %s (%s); defaulting injection-class " "index to 1 (unverified).",
            config_path,
            exc,
        )
        return 1
    id2label = config.get("id2label") or {}
    for key, label in id2label.items():
        lowered = str(label).lower()
        if any(match in lowered for match in positive_label_match):
            return int(key)
    logger.warning(
        "config.json at %s has no id2label entry containing %s; " "defaulting injection-class index to 1 (unverified).",
        config_path,
        " / ".join(repr(m) for m in positive_label_match),
    )
    return 1


class ClassifierOnnxEngine:
    """ONNX Runtime sequence-classifier engine (softmax over logits).

    ORT thread pools are capped BEFORE session construction so the session
    can never starve the event loop.

    Attributes:
        engine_name: Always ``"onnx"``.
        model_id: The resolved model id or local directory path.
    """

    engine_name = "onnx"

    def __init__(
        self,
        tokenizer_dir: Path,
        graph_path: Path,
        model_id: str,
        *,
        env_prefix: str = "PARROT_INJECTION",
        positive_label_match: tuple[str, ...] = ("inject",),
        max_length: int = DEFAULT_MAX_LENGTH,
    ) -> None:
        """Load tokenizer + thread-capped ORT session (never downloads; raises on failure).

        Args:
            tokenizer_dir: Local directory with tokenizer + config files.
            graph_path: Exact path to the ONNX graph.
            model_id: Identifier logged/reported as this engine's model.
            env_prefix: Prefix of the ``<P>_ORT_*_THREADS`` env variables.
            positive_label_match: Substrings identifying the positive class.
            max_length: Tokenizer truncation length.

        Raises:
            Exception: Any tokenizer/session construction failure.
        """
        import onnxruntime as ort

        self.model_id = model_id
        self._max_length = max_length
        self._tokenizer = load_tokenizer(tokenizer_dir)

        opts = ort.SessionOptions()
        intra = env_int(f"{env_prefix}_ORT_INTRA_OP_THREADS", 2)
        if intra > 0:
            opts.intra_op_num_threads = intra
        opts.inter_op_num_threads = env_int(f"{env_prefix}_ORT_INTER_OP_THREADS", 1)

        self._session = ort.InferenceSession(
            str(graph_path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self._input_names = {inp.name for inp in self._session.get_inputs()}
        self._positive_index = resolve_positive_index(tokenizer_dir, positive_label_match)

    def score(self, text: str) -> float:
        """Probability of the positive class for *text*."""
        encoded = self._tokenizer(
            text,
            return_tensors="np",
            truncation=True,
            max_length=self._max_length,
        )
        feed = {name: value for name, value in encoded.items() if name in self._input_names}
        logits = self._session.run(None, feed)[0]
        return float(softmax(logits[0])[self._positive_index])


# ---------------------------------------------------------------------------
# Generic per-category resolver + warm-up (new categories only).
# ---------------------------------------------------------------------------

_UNSET = object()
_RESOLVED: dict[str, Any] = {}
_RESOLVE_LOCK = threading.Lock()
_WARMUP_LOCKS: dict[str, asyncio.Lock] = {}
_WARMUP_DONE: set[str] = set()


def _model_id(spec: EngineSpec) -> str:
    return os.environ.get(f"{spec.env_prefix}_ONNX_MODEL") or spec.default_model_id


def _graph_repo_path(spec: EngineSpec) -> str:
    return os.environ.get(f"{spec.env_prefix}_ONNX_GRAPH") or spec.known_graph_paths.get(
        _model_id(spec), "onnx/model.onnx"
    )


def _build_engine(spec: EngineSpec, tokenizer_dir: Path, graph_path: Path, model_id: str) -> ScoringEngine:
    """Construct the engine for ``spec.kind`` (embedding kind added by TASK-4828)."""
    if spec.kind == "classifier":
        return ClassifierOnnxEngine(
            tokenizer_dir,
            graph_path,
            model_id,
            env_prefix=spec.env_prefix,
            positive_label_match=spec.positive_label_match,
            max_length=spec.max_length,
        )
    raise ValueError(f"engine kind {spec.kind!r} not supported yet")


def _env_dir_graph(spec: EngineSpec) -> tuple[Path, Path] | None:
    """Return ``(dir, graph)`` when ``<P>_ONNX_DIR`` is a usable dir, else ``None`` (silent)."""
    env_dir = os.environ.get(f"{spec.env_prefix}_ONNX_DIR")
    if not env_dir:
        return None
    path = Path(env_dir)
    graph = path / "model.onnx"
    if path.is_dir() and graph.exists():
        return path, graph
    return None


def _try_env_dir(spec: EngineSpec) -> ScoringEngine | None:
    var = f"{spec.env_prefix}_ONNX_DIR"
    env_dir = os.environ.get(var)
    if not env_dir:
        return None
    path = Path(env_dir)
    if not path.is_dir():
        logger.error("%s=%s is not a directory; falling back (category=%s).", var, env_dir, spec.category)
        return None
    graph = path / "model.onnx"
    if not graph.exists():
        logger.error("%s=%s is missing model.onnx; falling back (category=%s).", var, env_dir, spec.category)
        return None
    try:
        return _build_engine(spec, path, graph, str(path))
    except Exception as exc:  # noqa: BLE001 - degrade, never raise
        logger.error("Failed to construct engine from %s=%s: %s (category=%s).", var, env_dir, exc, spec.category)
        return None


def _try_cache(spec: EngineSpec) -> ScoringEngine | None:
    model_id = _model_id(spec)
    if not model_id:
        return None
    graph_repo_path = _graph_repo_path(spec)
    try:
        from huggingface_hub import try_to_load_from_cache

        cached = try_to_load_from_cache(model_id, graph_repo_path)
    except Exception as exc:  # noqa: BLE001 - offline probe must never raise
        logger.warning("Cache probe failed for %s (category=%s): %s", model_id, spec.category, exc)
        return None
    if not isinstance(cached, str):
        logger.warning(
            "No cached ONNX snapshot found for %s (category=%s); call warmup_model() to download it.",
            model_id,
            spec.category,
        )
        return None
    root = Path(cached)
    for _ in Path(graph_repo_path).parts:
        root = root.parent
    try:
        return _build_engine(spec, root, root / graph_repo_path, model_id)
    except Exception as exc:  # noqa: BLE001 - degrade, never raise
        logger.error("Failed to construct engine from cached snapshot %s: %s (category=%s).", root, exc, spec.category)
        return None


def _do_resolve(spec: EngineSpec) -> ScoringEngine | None:
    """Offline precedence: ``<P>_ONNX_DIR`` -> cached HF snapshot -> ``None``.

    Mirrors ``prompt_injection._do_resolve_injection_engine`` minus pytector;
    every failure logs and falls through. Never downloads, never raises.
    """
    try:
        engine = _try_env_dir(spec)
        source = f"{spec.env_prefix}_ONNX_DIR"
        if engine is None:
            engine = _try_cache(spec)
            source = "cached HF snapshot"
    except Exception as exc:  # noqa: BLE001 - belt and braces
        logger.error("Engine resolution failed (category=%s): %s", spec.category, exc)
        return None
    if engine is not None:
        logger.info(
            "selected engine=%s model=%s category=%s (%s)",
            engine.engine_name,
            engine.model_id,
            spec.category,
            source,
        )
    else:
        logger.info("no ML engine available (category=%s)", spec.category)
    return engine


def resolve_engine(spec: EngineSpec, force_reresolve: bool = False) -> ScoringEngine | None:
    """Memoized per ``spec.category``; thread-safe double-checked lock.

    Args:
        spec: The category's engine spec.
        force_reresolve: Bypass the memoized result and resolve again.

    Returns:
        The resolved engine, or ``None`` when no ML engine is available.
    """
    cached = _RESOLVED.get(spec.category, _UNSET)
    if cached is not _UNSET and not force_reresolve:
        return cached  # type: ignore[return-value]
    with _RESOLVE_LOCK:
        cached = _RESOLVED.get(spec.category, _UNSET)
        if cached is not _UNSET and not force_reresolve:
            return cached  # type: ignore[return-value]
        engine = _do_resolve(spec)
        _RESOLVED[spec.category] = engine
        return engine


def _download_snapshot(spec: EngineSpec, force_download: bool) -> None:
    if _env_dir_graph(spec) is not None:
        return
    model_id = _model_id(spec)
    if not model_id:
        logger.warning("warmup_model: no model id configured (category=%s); skipping download.", spec.category)
        return
    from huggingface_hub import snapshot_download

    snapshot_download(
        model_id,
        allow_patterns=[_graph_repo_path(spec), *spec.warmup_allow_patterns],
        force_download=force_download,
    )


async def warmup_model(spec: EngineSpec, force_download: bool = False) -> str:
    """Download (if needed), re-resolve and warm ``spec``'s engine; the ONLY download site.

    Args:
        spec: The category's engine spec.
        force_download: Re-fetch and re-resolve even if warm-up already ran.

    Returns:
        ``"onnx"`` or ``"none"``. Never raises; download/inference run in threads.
    """
    lock = _WARMUP_LOCKS.setdefault(spec.category, asyncio.Lock())
    async with lock:
        if spec.category in _WARMUP_DONE and not force_download:
            engine = resolve_engine(spec)
            return engine.engine_name if engine is not None else "none"
        try:
            await asyncio.to_thread(_download_snapshot, spec, force_download)
        except Exception as exc:  # noqa: BLE001 - warm-up degrades, never raises
            logger.error("warmup_model: download failed (category=%s): %s", spec.category, exc)
        engine = await asyncio.to_thread(resolve_engine, spec, True)
        if engine is not None:
            try:
                await asyncio.to_thread(engine.score, _WARMUP_DUMMY_TEXT)
            except Exception as exc:  # noqa: BLE001 - warm-up degrades, never raises
                logger.error("warmup_model: dummy inference failed (category=%s): %s", spec.category, exc)
        _WARMUP_DONE.add(spec.category)
        return engine.engine_name if engine is not None else "none"


def _reset_chassis_state() -> None:
    """Test hook: forget every memoized resolution and warm-up."""
    _RESOLVED.clear()
    _WARMUP_DONE.clear()
    _WARMUP_LOCKS.clear()
