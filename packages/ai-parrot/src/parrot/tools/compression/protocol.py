"""Frozen contract for the tool-result compression pipeline.

Defines :class:`CompressionOutcome` (the return value of every codec),
the :class:`ResultCompressor` Protocol every codec must satisfy, and the
process-wide codec-class registry (:func:`register_codec`,
:func:`get_codec`, :func:`known_codecs`).

This module has no dependency on the rest of ``parrot.tools`` — it exists
so third-party packages can implement ``ResultCompressor`` without
importing anything beyond stdlib/pydantic (G6), and so this package can be
imported without pulling in ``parrot.tools.manager``.
"""
import logging
from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel

from .levels import FilterLevel

logger = logging.getLogger(__name__)


class CompressionOutcome(BaseModel):
    """Result of a single codec's ``compress()`` call.

    Attributes:
        payload: The compressed result (or the original payload, unchanged,
            when the codec passed through).
        lossy: ``True`` when the transformation is not fully reversible from
            ``payload`` alone — the caller must tee the original payload to
            working memory so it stays recoverable (G3).
        bytes_before: Serialized size of the input, in bytes.
        bytes_after: Serialized size of ``payload``, in bytes.
        est_tokens_saved: ``bytes/4`` heuristic estimate of tokens saved.
            Approximate by design — no tokenizer is available to the
            pipeline.
        codec_name: Name of the codec that produced this outcome.
    """

    payload: Any
    lossy: bool
    bytes_before: int
    bytes_after: int
    est_tokens_saved: int
    codec_name: str


@runtime_checkable
class ResultCompressor(Protocol):
    """Structural contract every compression codec must satisfy.

    A plain ``Protocol`` (not an ABC) so third-party codecs need no
    ``parrot``-specific base class (G6, extensibility without touching
    core Python).
    """

    codec_name: ClassVar[str]

    def compress(
        self,
        result: Any,
        *,
        level: FilterLevel,
        params: dict[str, Any],
    ) -> CompressionOutcome:
        """Compress ``result`` at the given ``level``.

        Must be synchronous and deterministic (G4 — no LLM, no
        nondeterministic source): the inline path has a sub-millisecond
        budget and must never ``await``. Off-loop execution is the caller's
        decision (the latency-budget router), not the codec's.

        Args:
            result: The unserialized tool result to compress.
            level: The effective :class:`FilterLevel` to apply.
            params: Codec-specific parameters resolved from configuration.

        Returns:
            A :class:`CompressionOutcome` describing the transformation.
        """
        ...


_CODEC_REGISTRY: dict[str, type] = {}


def register_codec(cls: type) -> type:
    """Class decorator that registers a codec class by its ``codec_name``.

    Args:
        cls: A class satisfying the :class:`ResultCompressor` protocol,
            exposing a ``codec_name`` class attribute.

    Returns:
        ``cls`` unchanged (decorator pattern).

    Raises:
        ValueError: If a codec with the same ``codec_name`` is already
            registered.
    """
    codec_name = cls.codec_name
    if codec_name in _CODEC_REGISTRY:
        raise ValueError(
            f"Codec '{codec_name}' is already registered "
            f"(existing: {_CODEC_REGISTRY[codec_name]!r}, new: {cls!r})"
        )
    _CODEC_REGISTRY[codec_name] = cls
    logger.debug("Registered compression codec '%s' -> %s", codec_name, cls)
    return cls


def get_codec(name: str) -> type | None:
    """Look up a registered codec class by name.

    Args:
        name: The codec's ``codec_name``.

    Returns:
        The registered class, or ``None`` if no codec is registered under
        ``name``.
    """
    return _CODEC_REGISTRY.get(name)


def known_codecs() -> frozenset[str]:
    """Return the set of currently registered codec names.

    Returns:
        A frozen snapshot of registered ``codec_name`` values, used by the
        TOML config loader for load-time validation of ``codec`` entries.
    """
    return frozenset(_CODEC_REGISTRY.keys())
