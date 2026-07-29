"""``json_compact`` codec — MINIMAL-level, strictly lossless compression.

The default wildcard codec (see the core ``compressors.toml`` manifest):
every unconfigured deployment gets this at ``FilterLevel.MINIMAL`` (G2).
Because it is the zero-config baseline, the bar is losslessness, not
aggressiveness — ``lossy`` is always ``False`` for this codec.

Honest calibration (spec Sec 7): BPE tokenizers merge whitespace runs, so
expect roughly 5-15% *token* savings even when the byte diff looks larger.
The real return on investment is in ``NORMAL`` (the columnar codec,
TASK-1954).
"""
import logging
from typing import Any, ClassVar

from datamodel.parsers.json import json_encoder

from ..levels import FilterLevel
from ..protocol import CompressionOutcome, register_codec

logger = logging.getLogger(__name__)

# A list element shaped exactly like a dedup marker is never re-collapsed —
# doing so would be indistinguishable from a nested marker on decode.
_REPEAT_KEYS = frozenset({"_repeat", "_value"})


@register_codec
class JsonCompactCodec:
    """Lossless MINIMAL-level codec: separator compaction, null-key
    elision, and exact sibling dedup.

    Three transformations, all strictly lossless:

    1. **Separator compaction** — serialized with ``(",", ":")`` separators,
       no indentation, no trailing whitespace (delegated to
       ``datamodel.parsers.json.json_encoder``, the project serializer).
    2. **Null-key elision** — dict keys whose value is ``None`` are dropped,
       recursively. An all-null dict becomes ``{}`` rather than being
       dropped itself, preserving structure/arity at the parent level.
    3. **Exact dedup** — runs of 2+ structurally identical, consecutive
       list elements collapse to ``{"_repeat": N, "_value": <element>}``.
       Applied only when the collapse is unambiguous and round-trippable.
    """

    codec_name: ClassVar[str] = "json_compact"

    def compress(
        self, result: Any, *, level: FilterLevel, params: dict[str, Any],
    ) -> CompressionOutcome:
        """Compress ``result`` at ``level``. See class docstring.

        Args:
            result: The unwrapped tool result payload.
            level: Effective :class:`FilterLevel`. ``NONE`` is a strict
                passthrough (same object, unchanged sizes).
            params: Codec params. Recognized key: ``dedup`` (bool, default
                ``True``) — disable the exact-dedup transformation.

        Returns:
            A :class:`CompressionOutcome` with ``lossy`` always ``False``.
        """
        if level is FilterLevel.NONE:
            size = self._safe_size(result) or 0
            return self._outcome(result, size, size)

        before = self._safe_size(result)
        if before is None:
            # Non-serializable payload: nothing this codec can safely do.
            return self._outcome(result, 0, 0)

        try:
            payload = self._elide_nulls(result)
            if params.get("dedup", True):
                payload = self._dedup_siblings(payload)
            after = self._safe_size(payload)
            if after is None:
                # Defensive: transformed payload somehow not serializable.
                return self._outcome(result, before, before)
        except Exception:
            # Never break a tool call — defense in depth (the stage also
            # guards codec exceptions, TASK-1951).
            logger.warning(
                "json_compact codec raised during compression; passing "
                "through the original payload.", exc_info=True,
            )
            return self._outcome(result, before, before)

        return CompressionOutcome(
            payload=payload,
            lossy=False,
            bytes_before=before,
            bytes_after=after,
            est_tokens_saved=max(0, before - after) // 4,
            codec_name=self.codec_name,
        )

    @staticmethod
    def _safe_size(value: Any) -> int | None:
        """Return the serialized size of ``value`` in bytes, or ``None``
        if it is not JSON-serializable via the project serializer."""
        try:
            return len(json_encoder(value).encode("utf-8"))
        except Exception:
            return None

    def _outcome(self, payload: Any, before: int, after: int) -> CompressionOutcome:
        """Build a no-op / passthrough outcome (``lossy=False``)."""
        return CompressionOutcome(
            payload=payload, lossy=False, bytes_before=before,
            bytes_after=after, est_tokens_saved=0, codec_name=self.codec_name,
        )

    @classmethod
    def _elide_nulls(cls, value: Any) -> Any:
        """Recursively drop dict keys whose value is ``None``.

        An all-null dict becomes ``{}`` (kept, not dropped), so the
        structure/arity of the parent container is unchanged.
        """
        if isinstance(value, dict):
            return {
                key: cls._elide_nulls(v)
                for key, v in value.items()
                if v is not None
            }
        if isinstance(value, list):
            return [cls._elide_nulls(v) for v in value]
        return value

    @classmethod
    def _dedup_siblings(cls, value: Any) -> Any:
        """Recursively collapse runs of 2+ identical, consecutive list
        elements into a ``{"_repeat": N, "_value": element}`` marker."""
        if isinstance(value, dict):
            return {k: cls._dedup_siblings(v) for k, v in value.items()}
        if isinstance(value, list):
            return cls._collapse_repeats([cls._dedup_siblings(v) for v in value])
        return value

    @classmethod
    def _collapse_repeats(cls, items: list[Any]) -> list[Any]:
        """Collapse consecutive structurally-equal runs of length >= 2."""
        result: list[Any] = []
        i, n = 0, len(items)
        while i < n:
            j = i + 1
            while j < n and cls._structurally_equal(items[j], items[i]):
                j += 1
            run_len = j - i
            if run_len >= 2 and cls._collapsible(items[i]):
                result.append({"_repeat": run_len, "_value": items[i]})
            else:
                result.extend(items[i:j])
            i = j
        return result

    @staticmethod
    def _structurally_equal(a: Any, b: Any) -> bool:
        try:
            return a == b
        except Exception:
            return False

    @staticmethod
    def _collapsible(value: Any) -> bool:
        """Guard against ambiguous re-collapse of an already-marker-shaped
        value (would be indistinguishable from a nested marker on decode)."""
        if isinstance(value, dict) and set(value.keys()) == _REPEAT_KEYS:
            return False
        return True
