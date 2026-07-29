"""``columnar`` codec — row-oriented ``list[dict]`` -> split columnar form.

The codec that pays for the feature (spec Sec 3 Module 4). The most
expensive known case is ``DatabaseQueryToolkit``: ``QueryResult.rows`` is
``list[dict[str, Any]]``, so N column names repeat in each of M rows — for
500 rows x 12 columns that is ~6,000 repetitions of field names the model
only needs to see once.

Output shape is **deliberately identical to ``PandasTable``**
(``parrot/bots/data.py:70``), which the ``PandasAgentResponse`` prompt
already teaches the LLM to read — no new prompt engineering needed. Its
shape is NOT imported here (that would invert the dependency direction);
only matched.

This pure-Python implementation is the **executable specification**: the
optional Rust path (TASK-1955, ``parrot_codec``) must pass this exact test
suite byte-for-byte.

Rust dispatch (TASK-1955): only a ``bytes``/``str`` ``result`` — an
ALREADY-serialized JSON row array (or ``QueryResult``-shaped JSON object)
— is eligible for the Rust transform, in a single FFI crossing. A native
``dict``/``list`` result NEVER crosses the FFI boundary: per-row
``extract()`` under the GIL can be slower than pure Python, so crossing
with materialized Python objects would be a pessimization (spec Sec 3
Module 6). The Rust extension is entirely optional (G8) — absent, this
module logs exactly once at debug and every call takes the pure-Python
path below.
"""
import logging
from typing import Any, ClassVar

from datamodel.parsers.json import json_decoder, json_encoder

from parrot._imports import lazy_import

from ..levels import FilterLevel
from ..protocol import CompressionOutcome, register_codec

logger = logging.getLogger(__name__)

_DEFAULT_MIN_ROWS = 20
_DEFAULT_HETEROGENEITY_RATIO = 1.5

# Runtime detection of the optional `parrot_codec` Rust extension —
# detected once per process, cached, logged at most once at `debug`
# (never per call). Kept LOCAL to this module (distinct from
# `budget.is_rust_available()`, which informs the router's inline/
# executor/passthrough decision): this cache answers "can THIS codec
# actually call into Rust for this call", not "is the extension present
# at all" (the two questions happen to share an answer today, but are
# conceptually separate call sites).
_RUST = None
_RUST_CHECKED = False


def _rust():
    """Return the `parrot_codec` module if available, else `None`.
    Detected once; absence logged exactly once at `debug`."""
    global _RUST, _RUST_CHECKED
    if not _RUST_CHECKED:
        _RUST_CHECKED = True
        try:
            _RUST = lazy_import("parrot_codec")
        except Exception:
            logger.debug(
                "parrot_codec extension not available; columnar codec uses "
                "the pure-Python path."
            )
    return _RUST


@register_codec
class ColumnarCodec:
    """Row-oriented ``list[dict]`` -> column-split ``{columns, rows,
    constants}`` form.

    Transformations:

    1. **Column extraction** — keys hoisted once into ``columns`` (stable,
       first-seen order across rows — never ``set`` iteration order, G4);
       values become positional lists aligned to ``columns``.
    2. **Constant-column factoring** — a column whose value is identical
       across every row (when there is more than one row) moves to
       ``constants`` and drops out of ``columns``/``rows``.
    3. **Null-column elision** — an all-null column is dropped entirely
       (logged for discoverability).

    Passthrough guards, each a "no gain" outcome:

    - fewer than ``min_rows`` rows (default 20, per-tool configurable via
      ``params``) — the ORIGINAL object is returned unchanged.
    - heterogeneous rows (key union/intersection ratio > 1.5, configurable)
      — null-key elision only, no columnarization.
    - any nested ``dict``/``list`` value — no flattening; null-key elision
      only.
    - non-``list[dict]`` (and non-``QueryResult``-shaped) input — unchanged
      passthrough.

    Accepts a bare ``list[dict]`` OR a ``QueryResult``-shaped dict (a dict
    with a ``rows`` key holding ``list[dict]``): only ``rows`` is
    transformed, sibling fields (``driver``, ``row_count``, ``columns``,
    ``execution_time_ms``, ...) are left untouched. Also accepts the same
    two shapes pre-serialized as ``bytes``/``str`` (JSON) — the ONLY input
    form eligible for the optional Rust transform (see module docstring).
    """

    codec_name: ClassVar[str] = "columnar"

    def compress(
        self, result: Any, *, level: FilterLevel, params: dict[str, Any],
    ) -> CompressionOutcome:
        """Compress ``result``. See class docstring for the transformation
        and passthrough-guard rules.

        Args:
            result: The unwrapped tool result payload — a ``list[dict]``,
                a ``QueryResult``-shaped ``dict``, or either pre-serialized
                as ``bytes``/``str`` JSON.
            level: Effective :class:`FilterLevel`. ``NONE`` is a strict
                passthrough.
            params: Recognized keys: ``min_rows`` (int, default 20),
                ``heterogeneity_ratio`` (float, default 1.5).

        Returns:
            A :class:`CompressionOutcome`. ``lossy`` is ``True`` whenever
            constant factoring or null elision dropped anything (arms the
            tee, TASK-1953); ``False`` for a pure shape change with no
            information dropped, or any passthrough. ``payload`` is always
            a native Python object (never re-encoded to bytes/str, even
            when the input was bytes/str).
        """
        if level is FilterLevel.NONE:
            return self._passthrough(result)

        try:
            before = self._safe_size(result)
            if before is None:
                return self._passthrough(result, 0)

            min_rows = int(params.get("min_rows", _DEFAULT_MIN_ROWS))
            het_ratio = float(
                params.get("heterogeneity_ratio", _DEFAULT_HETEROGENEITY_RATIO)
            )

            # Bytes/str input: decode once to evaluate the guards below.
            # The ORIGINAL bytes are kept so the Rust dispatch decision
            # (further down) is based on the INPUT's type, not on what we
            # could technically re-serialize — a native dict/list result
            # NEVER crosses the FFI boundary, full stop.
            raw_bytes = self._as_bytes_if_serialized(result)
            working = self._decode(raw_bytes) if raw_bytes is not None else result
            if working is None:
                return self._passthrough(result, before)

            rows, container_key = self._locate_rows(working)
            if rows is None or len(rows) < min_rows:
                return self._passthrough(result, before)

            if self._is_heterogeneous(rows, het_ratio) or self._has_nested_values(rows):
                return self._null_elision_only(working, rows, container_key, before)

            original_columns = self._first_seen_columns(rows)
            transformed = self._dispatch_columnarize(rows, container_key, raw_bytes, min_rows)
            kept = set(transformed["columns"]) | set(transformed["constants"])
            dropped_or_factored = [c for c in original_columns if c not in kept]
            if dropped_or_factored:
                logger.debug(
                    "columnar codec dropped/factored columns: %s",
                    dropped_or_factored,
                )

            payload = self._rewrap(working, container_key, transformed)
            after = self._safe_size(payload)
            if after is None:
                return self._passthrough(result, before)

            return CompressionOutcome(
                payload=payload,
                lossy=bool(dropped_or_factored),
                bytes_before=before,
                bytes_after=after,
                est_tokens_saved=max(0, before - after) // 4,
                codec_name=self.codec_name,
            )
        except Exception:
            # Never break a tool call — defense in depth (the stage also
            # guards codec exceptions, TASK-1951).
            logger.warning(
                "columnar codec raised during compression; passing through "
                "the original payload.", exc_info=True,
            )
            return self._passthrough(result)

    def _dispatch_columnarize(
        self,
        rows: list[dict],
        container_key: "str | None",
        raw_bytes: "bytes | None",
        min_rows: int,
    ) -> dict[str, Any]:
        """Run the core columnarization, via Rust when eligible+available,
        else the pure-Python reference path. Both MUST produce identical
        ``{"columns", "rows", "constants"}`` output for the same input
        (TASK-1954's suite is the executable spec both must satisfy)."""
        if raw_bytes is not None:
            rust = _rust()
            if rust is not None:
                # A bare row-array input crosses with NO re-serialization
                # (the original bytes ARE the row array); a QueryResult-
                # shaped input re-serializes only the `rows` sub-array —
                # the outer QueryResult shell never crosses the FFI
                # boundary either way. Single crossing for the transform.
                rows_bytes = raw_bytes if container_key is None else (
                    json_encoder(rows).encode("utf-8")
                )
                out_bytes = rust.columnarize(rows_bytes, min_rows)
                return json_decoder(out_bytes.decode("utf-8"))

        columns, out_rows, constants, _null_cols, _factored_cols = self._columnarize(rows)
        return {"columns": columns, "rows": out_rows, "constants": constants}

    # -- passthrough / size / (de)serialization helpers -------------------

    @staticmethod
    def _safe_size(value: Any) -> "int | None":
        """Serialized size of ``value`` in bytes, or ``None`` if it is not
        JSON-serializable via the project serializer."""
        try:
            return len(json_encoder(value).encode("utf-8"))
        except Exception:
            return None

    @staticmethod
    def _passthrough(payload: Any, before: "int | None" = None) -> CompressionOutcome:
        """A no-op outcome: the SAME object, unchanged, ``lossy=False``."""
        size = before if before is not None else (ColumnarCodec._safe_size(payload) or 0)
        return CompressionOutcome(
            payload=payload, lossy=False, bytes_before=size, bytes_after=size,
            est_tokens_saved=0, codec_name=ColumnarCodec.codec_name,
        )

    @staticmethod
    def _as_bytes_if_serialized(result: Any) -> "bytes | None":
        """Return UTF-8 bytes when ``result`` is already ``bytes``/``str``
        (the only input form eligible for the Rust dispatch), else
        ``None``."""
        if isinstance(result, bytes):
            return result
        if isinstance(result, str):
            return result.encode("utf-8")
        return None

    @staticmethod
    def _decode(raw_bytes: bytes) -> Any:
        """Decode JSON bytes into a native Python object, or ``None`` on
        failure (never raises — the caller treats ``None`` as "not a
        recognizable payload shape", not an error)."""
        try:
            return json_decoder(raw_bytes.decode("utf-8"))
        except Exception:
            return None

    # -- row location / shape detection --------------------------------

    @staticmethod
    def _locate_rows(result: Any) -> "tuple[list | None, str | None]":
        """Locate the ``list[dict]`` of rows to transform.

        Returns:
            ``(rows, container_key)``. ``container_key`` is ``None`` for a
            bare ``list[dict]`` input, or ``"rows"`` for a
            ``QueryResult``-shaped dict input. ``(None, None)`` when
            ``result`` does not match either shape.
        """
        if isinstance(result, list):
            if result and all(isinstance(r, dict) for r in result):
                return result, None
            return None, None
        if isinstance(result, dict):
            rows = result.get("rows")
            if isinstance(rows, list) and rows and all(isinstance(r, dict) for r in rows):
                return rows, "rows"
        return None, None

    @staticmethod
    def _rewrap(result: Any, container_key: "str | None", transformed: Any) -> Any:
        """Re-embed ``transformed`` into ``result`` at ``container_key``,
        leaving sibling fields untouched; returns ``transformed`` directly
        for a bare-list input (``container_key is None``)."""
        if container_key is None:
            return transformed
        new_result = dict(result)
        new_result[container_key] = transformed
        return new_result

    @staticmethod
    def _is_heterogeneous(rows: list[dict], het_ratio: float) -> bool:
        """True when rows' key sets are mostly disjoint (union/intersection
        ratio exceeds ``het_ratio``, or there is no shared key at all)."""
        key_sets = [set(r.keys()) for r in rows]
        union = set().union(*key_sets)
        inter = set.intersection(*key_sets)
        if not inter:
            return True
        return (len(union) / len(inter)) > het_ratio

    @staticmethod
    def _has_nested_values(rows: list[dict]) -> bool:
        """True when any row value is itself a ``dict``/``list`` (no
        flattening is attempted — null-elision only in that case)."""
        return any(isinstance(v, (dict, list)) for row in rows for v in row.values())

    # -- transformations -------------------------------------------------

    @staticmethod
    def _null_elision_only(
        result: Any, rows: list[dict], container_key: "str | None", before: int,
    ) -> CompressionOutcome:
        """Drop ``None``-valued keys per row, without columnarizing
        (heterogeneous or deeply-nested rows)."""
        new_rows = [{k: v for k, v in row.items() if v is not None} for row in rows]
        payload = ColumnarCodec._rewrap(result, container_key, new_rows)
        after = ColumnarCodec._safe_size(payload)
        if after is None:
            return ColumnarCodec._passthrough(result, before)
        lossy = any(len(new) != len(old) for new, old in zip(new_rows, rows))
        return CompressionOutcome(
            payload=payload, lossy=lossy, bytes_before=before, bytes_after=after,
            est_tokens_saved=max(0, before - after) // 4, codec_name="columnar",
        )

    @staticmethod
    def _first_seen_columns(rows: list[dict]) -> list[str]:
        """Column names in first-seen order across ``rows`` (each row's own
        key order) — never ``set`` iteration order (G4: determinism)."""
        columns: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    seen.add(key)
                    columns.append(key)
        return columns

    @staticmethod
    def _columnarize(
        rows: list[dict],
    ) -> "tuple[list[str], list[list[Any]], dict[str, Any], list[str], list[str]]":
        """Split ``rows`` into ``(columns, out_rows, constants, null_cols,
        factored_cols)`` — the pure-Python reference implementation the
        optional Rust path (TASK-1955) must match byte-for-byte."""
        columns = ColumnarCodec._first_seen_columns(rows)

        null_cols = [c for c in columns if all(row.get(c) is None for row in rows)]
        columns = [c for c in columns if c not in null_cols]

        constants: dict[str, Any] = {}
        factored_cols: list[str] = []
        if len(rows) > 1:
            for col in list(columns):
                values = [row.get(col) for row in rows]
                first = values[0]
                if all(v == first for v in values):
                    constants[col] = first
                    factored_cols.append(col)
            if factored_cols:
                columns = [c for c in columns if c not in factored_cols]

        out_rows = [[row.get(c) for c in columns] for row in rows]
        return columns, out_rows, constants, null_cols, factored_cols
