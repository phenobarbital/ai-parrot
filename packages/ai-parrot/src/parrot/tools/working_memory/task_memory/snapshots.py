"""Bounded evidence snapshots and deterministic fingerprints (FEAT-538).

Implements §2 *Catalog Backend, Versions, and Evidence* of the approved
specification. Registering a value as task evidence has to answer three
questions honestly, and this module is where they are answered:

1. **Is the snapshot really independent of the live value?** Only then can
   a later mutation of the caller's object be detected instead of silently
   following it.
2. **Does the fingerprint actually prove content integrity?** A digest you
   *can* compute is not the same as a digest that *means* something.
3. **How many bytes are we really retaining?** An estimate must be
   labelled an estimate.

Phase 0 (TASK-2970) measured the traps this module exists to avoid:

- ``pandas`` does **not** raise on unhashable object cells. It silently
  hashes their ``str`` repr, so ``hash_pandas_object`` happily returns a
  digest for a column of ``dict``s. That digest is worthless as integrity
  proof — it even changes when a dict's *key order* changes while its
  content does not.
- ``DataFrame.copy(deep=True)`` does **not** detach nested ``dict`` /
  ``list`` / ``set`` cells. Verified by object identity at 8/64/256 MiB:
  ``df["obj"].iloc[0] is snapshot["obj"].iloc[0]`` is ``True``.
- Column **name** changes do not alter row hashes, so the ordered column
  names must be folded into the fingerprint header explicitly.
- Fingerprinting dominates cost (~9.5 s for a 256 MiB numeric frame,
  ~123 s for a nested-object one) while the copy is nearly free. Heavy
  work therefore goes through :func:`capture_snapshot_async`, and no
  caller may hold a lock across it.

Consequently: a frame carrying nested mutable object cells is reported
:data:`SnapshotOutcome.UNVERIFIABLE` with ``evidence_verifiable=False``,
**even though a fingerprint could have been computed for it**. Refusing
to launder a repr hash into an integrity claim is the entire point.

.. warning::

   Delivery A is **not durable**. A captured snapshot lives in this
   process only. :data:`SnapshotOutcome.SPILL_REQUIRED` reports that a
   supported value exceeded the RAM cap and needs the durable tier; this
   module never writes bytes anywhere itself.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import decimal
import hashlib
import logging
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Set, Tuple, Type

import numpy as np
import orjson
import pandas as pd

from .models import ArtifactKind, Limits, TaskMemoryError

__all__ = (
    "FINGERPRINT_ALGORITHM",
    "FINGERPRINT_PREFIX",
    "CHECKSUM_PREFIX",
    "CHECKSUM_ALGORITHM",
    "MAX_SUMMARY_COLUMNS",
    "UnsupportedEvidence",
    "SnapshotOutcome",
    "SizeMethod",
    "ByteAccount",
    "ContentSnapshot",
    "detect_kind",
    "canonical_json_bytes",
    "fingerprint_bytes",
    "fingerprint_dataframe",
    "blob_checksum",
    "unsafe_object_columns",
    "dataframe_schema_summary",
    "capture_snapshot",
    "capture_snapshot_async",
)

logger = logging.getLogger(__name__)

#: Identity **and version** of the content-fingerprint rules. Stored
#: alongside every fingerprint so a future rule change is detectable
#: rather than silently producing mismatches.
FINGERPRINT_ALGORITHM: str = "blake2b-8/v1"

#: Prefix for a canonical *content* fingerprint.
FINGERPRINT_PREFIX: str = "fp_"

#: Prefix for a *blob* checksum. Deliberately different from
#: :data:`FINGERPRINT_PREFIX`: a hash of Parquet bytes and a hash of
#: pandas content answer different questions and must never be compared.
CHECKSUM_PREFIX: str = "ck_"

#: Identity and version of the blob-checksum rules.
CHECKSUM_ALGORITHM: str = "blake2b-8-blob/v1"

#: BLAKE2b digest size, in bytes, for both fingerprints and checksums.
_DIGEST_SIZE: int = 8

#: Most columns described in a captured schema summary. The summary is
#: additionally bounded by :data:`Limits.MAX_SCHEMA_SUMMARY_BYTES`.
MAX_SUMMARY_COLUMNS: int = 100

#: Types whose instances cannot be mutated behind a snapshot's back, and
#: whose canonical rendering is stable.
#:
#: ``tuple`` and ``frozenset`` are deliberately **excluded** even though
#: they are immutable containers: a tuple may hold a ``dict``, and a
#: frozenset's iteration order is not guaranteed stable across processes.
#: Being conservative here costs a little coverage; being permissive
#: would cost correctness of an integrity claim.
_IMMUTABLE_SCALARS: Tuple[Type[Any], ...] = (
    type(None),
    bool,
    int,
    float,
    complex,
    str,
    bytes,
    decimal.Decimal,
    _dt.date,
    _dt.datetime,
    _dt.time,
    _dt.timedelta,
    uuid.UUID,
    np.generic,
)


class UnsupportedEvidence(TaskMemoryError):
    """A value has no reproducible canonical fingerprint.

    Raised by the low-level fingerprint helpers. The high-level
    :func:`capture_snapshot` catches it and returns an explicit
    unverifiable :class:`ContentSnapshot` instead — an unsupported value
    is a *result*, not a crash.
    """


class SnapshotOutcome(str, Enum):
    """What happened when a value was offered as evidence."""

    #: An independent snapshot was retained and fingerprinted.
    CAPTURED = "captured"
    #: Supported evidence that exceeded the RAM cap. Nothing was copied.
    #: The caller's durable tier should take it; without one it cannot be
    #: retained and must be recorded unverifiable.
    SPILL_REQUIRED = "spill_required"
    #: The value cannot carry a meaningful integrity claim.
    UNVERIFIABLE = "unverifiable"


class SizeMethod(str, Enum):
    """How a byte count was obtained — and therefore how much it is worth."""

    #: Length of the canonical UTF-8 encoding. Exact.
    CANONICAL_UTF8 = "canonical_utf8"
    #: Length of an immutable ``bytes`` value. Exact.
    RAW_BYTES = "raw_bytes"
    #: ``DataFrame.memory_usage(deep=True)``. An **estimate**: it does not
    #: account for interned strings shared with other objects, nor for
    #: objects referenced by but not owned by the frame.
    PANDAS_DEEP_ESTIMATE = "pandas_deep_estimate"
    #: The value's footprint could not be established at all. Notably this
    #: is what an arbitrary object gets: ``sys.getsizeof`` reports the
    #: shallow container only and never proves an object fits.
    UNKNOWN = "unknown"

    @property
    def is_exact(self) -> bool:
        """Whether this method yields a true byte count rather than an estimate."""
        return self in (SizeMethod.CANONICAL_UTF8, SizeMethod.RAW_BYTES)


@dataclass(frozen=True)
class ByteAccount:
    """Byte accounting for one candidate piece of evidence.

    Live and snapshot copies are counted **separately** because both may
    be resident at once — that is exactly the doubling the spec warns
    about.

    Attributes:
        live_bytes: Footprint of the caller's value, or ``None`` when it
            could not be established.
        snapshot_bytes: Footprint of the retained snapshot. ``0`` when no
            snapshot was retained.
        method: How the counts were obtained.
    """

    live_bytes: Optional[int]
    snapshot_bytes: int
    method: SizeMethod

    @property
    def exact(self) -> bool:
        """Whether these counts are measured rather than estimated."""
        return self.method.is_exact

    @property
    def total_retained(self) -> int:
        """Bytes this registration adds while both copies are resident."""
        return (self.live_bytes or 0) + self.snapshot_bytes


@dataclass(frozen=True)
class ContentSnapshot:
    """The full, honest outcome of offering a value as task evidence.

    Attributes:
        kind: Detected evidence type.
        outcome: What happened.
        payload: The detached snapshot, when one was retained. ``None``
            otherwise — a refusal never smuggles the value out.
        fingerprint: Canonical content fingerprint, when the value has a
            meaningful one.
        fingerprint_algorithm: :data:`FINGERPRINT_ALGORITHM` when a
            fingerprint is present.
        evidence_verifiable: Whether the fingerprint actually proves
            content integrity. ``False`` whenever the digest would be a
            repr hash, the kind is unsupported, or no snapshot backs it.
        account: Byte accounting.
        shape: Captured shape, e.g. ``(rows, cols)``.
        schema_summary: Bounded structural description.
        reason: Why the value is unverifiable or needs spilling.
    """

    kind: ArtifactKind
    outcome: SnapshotOutcome
    payload: Optional[Any]
    fingerprint: Optional[str]
    fingerprint_algorithm: Optional[str]
    evidence_verifiable: bool
    account: ByteAccount
    shape: Optional[Tuple[int, ...]]
    schema_summary: Optional[Dict[str, Any]]
    reason: Optional[str]

    @property
    def captured(self) -> bool:
        """Whether an independent snapshot is being retained."""
        return self.outcome is SnapshotOutcome.CAPTURED


# ─────────────────────────────────────────────────────────────
# Kind detection
# ─────────────────────────────────────────────────────────────


def detect_kind(value: Any) -> ArtifactKind:
    """Classify a value's evidence type.

    Args:
        value: The value being offered as evidence.

    Returns:
        The matching :class:`~parrot.tools.working_memory.task_memory.
        models.ArtifactKind`. Anything not recognised is
        :data:`ArtifactKind.OBJECT`, which can never carry verifiable
        evidence.
    """
    if isinstance(value, pd.DataFrame):
        return ArtifactKind.DATAFRAME
    if isinstance(value, str):
        return ArtifactKind.TEXT
    if isinstance(value, (bytes, bytearray, memoryview)):
        return ArtifactKind.BINARY
    if isinstance(value, (dict, list)):
        return ArtifactKind.JSON
    return ArtifactKind.OBJECT


# ─────────────────────────────────────────────────────────────
# Canonical serialization and fingerprints
# ─────────────────────────────────────────────────────────────


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize ``value`` to canonical UTF-8 JSON with sorted keys.

    Uses ``orjson`` with ``OPT_SORT_KEYS`` — measured byte-identical to
    the stdlib encoder for this subset and roughly 40x faster (1.6 s vs
    65 s at 256 MiB, TASK-2970).

    Serialization is **strict** in two respects, both deliberate:

    - No ``default=`` fallback. Coercing an unserializable object to its
      ``repr`` would produce a digest that looks authoritative while
      proving nothing, which is the exact failure mode this module exists
      to prevent.
    - No ``OPT_NON_STR_KEYS``. That option stringifies keys, so
      ``{1: "a"}`` and ``{"1": "a"}`` would encode to identical bytes and
      earn identical fingerprints despite being different values. A
      fingerprint that equates distinct content is worse than no
      fingerprint, so non-string keys are rejected instead.

    Args:
        value: A JSON-serializable value.

    Returns:
        The canonical encoding.

    Raises:
        UnsupportedEvidence: If ``value`` cannot be serialized strictly.
    """
    try:
        return orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    except (TypeError, ValueError) as exc:
        raise UnsupportedEvidence(f"value is not strictly JSON-serializable: {exc}") from exc


def fingerprint_bytes(data: bytes) -> str:
    """Fingerprint canonical bytes (JSON and text evidence).

    Args:
        data: Canonical UTF-8 bytes.

    Returns:
        :data:`FINGERPRINT_PREFIX` followed by a 16-hex-character
        BLAKE2b-8 digest.
    """
    return f"{FINGERPRINT_PREFIX}{hashlib.blake2b(data, digest_size=_DIGEST_SIZE).hexdigest()}"


def fingerprint_dataframe(df: pd.DataFrame) -> str:
    """Fingerprint a DataFrame's canonical content.

    Canonical content is the ordered structural header — shape, ordered
    column names, dtypes, index names and index dtype — followed by
    stable per-row hashes including the index. The header is **not**
    optional: measured on pandas 2.2.3, renaming a column does not change
    ``hash_pandas_object``'s output at all, so a fingerprint built from
    row hashes alone would call two differently-shaped frames identical.

    Never touches ``compact_summary()``, ``describe()`` or an object's
    ``repr()``.

    Args:
        df: The frame to fingerprint.

    Returns:
        :data:`FINGERPRINT_PREFIX` followed by a 16-hex-character
        BLAKE2b-8 digest.

    Raises:
        UnsupportedEvidence: If pandas cannot hash the frame's values —
            for example a column of ``list`` cells, which raises rather
            than repr-hashing.

    Note:
        A *successful* return does not by itself mean the digest is
        meaningful. For a frame with nested mutable object cells pandas
        hashes the cells' ``repr``, and that digest is not integrity
        proof. :func:`capture_snapshot` applies
        :func:`unsafe_object_columns` and refuses the verifiability claim
        in that case; callers computing a fingerprint directly must do
        the same.
    """
    digest = hashlib.blake2b(digest_size=_DIGEST_SIZE)
    header = {
        "algorithm": FINGERPRINT_ALGORITHM,
        "shape": [int(df.shape[0]), int(df.shape[1])],
        "columns": [str(column) for column in df.columns],
        "dtypes": [str(dtype) for dtype in df.dtypes],
        "index_names": [str(name) for name in df.index.names],
        "index_dtype": str(df.index.dtype),
    }
    digest.update(canonical_json_bytes(header))

    try:
        row_hashes = pd.util.hash_pandas_object(df, index=True, categorize=False)
    except Exception as exc:  # noqa: BLE001 — any hashing failure is one answer
        raise UnsupportedEvidence(f"DataFrame values cannot be hashed: {exc}") from exc

    digest.update(np.ascontiguousarray(row_hashes.to_numpy(dtype="uint64")).tobytes())
    return f"{FINGERPRINT_PREFIX}{digest.hexdigest()}"


def blob_checksum(data: bytes) -> str:
    """Checksum stored *blob* bytes — **not** a content fingerprint.

    A blob checksum answers "did these bytes survive the round trip to
    storage intact". A content fingerprint answers "is this the same
    logical content". They are not interchangeable: the Parquet encoding
    of a frame has a different checksum on every write, while the frame's
    content fingerprint is stable. The distinct
    :data:`CHECKSUM_PREFIX` exists so the two can never be silently
    compared.

    Args:
        data: The exact bytes written to or read from storage.

    Returns:
        :data:`CHECKSUM_PREFIX` followed by a 16-hex-character BLAKE2b-8
        digest.
    """
    return f"{CHECKSUM_PREFIX}{hashlib.blake2b(data, digest_size=_DIGEST_SIZE).hexdigest()}"


# ─────────────────────────────────────────────────────────────
# Safety analysis
# ─────────────────────────────────────────────────────────────


def unsafe_object_columns(df: pd.DataFrame) -> Tuple[str, ...]:
    """Return the object-dtype columns that block a verifiable snapshot.

    A column is unsafe when any of its values is not an immutable scalar.
    Two independent problems make such a column unusable as evidence, and
    either one alone is disqualifying:

    - ``copy(deep=True)`` does not detach it, so the "snapshot" still
      aliases the caller's mutable object.
    - pandas hashes it by ``repr``, so the digest tracks formatting
      rather than content.

    Args:
        df: The frame to analyse.

    Returns:
        Names of the offending columns, in column order. Empty when every
        column is safe.
    """
    unsafe: list[str] = []
    for column in df.columns:
        series = df[column]
        if series.dtype != object:
            continue
        # One pass collecting distinct types: cheap even for large frames
        # and, unlike sampling, it cannot give a false all-clear.
        present: Set[Type[Any]] = set(map(type, series.to_numpy()))
        if any(not issubclass(kind, _IMMUTABLE_SCALARS) for kind in present):
            unsafe.append(str(column))
    return tuple(unsafe)


def dataframe_schema_summary(df: pd.DataFrame) -> Dict[str, Any]:
    """Describe a frame's structure within the schema-summary byte bound.

    Records structure only — no values, no statistics, no previews.

    Args:
        df: The frame to describe.

    Returns:
        A summary that serializes within
        :data:`Limits.MAX_SCHEMA_SUMMARY_BYTES`. When the frame has too
        many columns the list is truncated and ``columns_truncated`` says
        so, rather than the summary being dropped or the bound breached.
    """
    columns = [str(column) for column in df.columns]
    dtypes = [str(dtype) for dtype in df.dtypes]
    keep = min(len(columns), MAX_SUMMARY_COLUMNS)

    def _build(count: int) -> Dict[str, Any]:
        return {
            "column_count": len(columns),
            "columns": columns[:count],
            "dtypes": dict(zip(columns[:count], dtypes[:count])),
            "index_names": [str(name) for name in df.index.names],
            "index_dtype": str(df.index.dtype),
            "columns_truncated": count < len(columns),
        }

    summary = _build(keep)
    # Long column names can still breach the byte bound; shrink until it
    # fits rather than letting ArtifactDescriptor reject the descriptor.
    while keep > 0 and len(canonical_json_bytes(summary)) > Limits.MAX_SCHEMA_SUMMARY_BYTES:
        keep //= 2
        summary = _build(keep)
    return summary


def _json_schema_summary(value: Any) -> Dict[str, Any]:
    """Describe a JSON value's top-level structure.

    Args:
        value: A ``dict`` or ``list``.

    Returns:
        A bounded structural summary carrying no values.
    """
    if isinstance(value, dict):
        keys = [str(key) for key in value][:MAX_SUMMARY_COLUMNS]
        summary: Dict[str, Any] = {
            "container": "object",
            "key_count": len(value),
            "keys": keys,
            "keys_truncated": len(value) > len(keys),
        }
    else:
        summary = {
            "container": "array",
            "length": len(value),
            "element_types": sorted({type(item).__name__ for item in value[:MAX_SUMMARY_COLUMNS]}),
        }
    while len(canonical_json_bytes(summary)) > Limits.MAX_SCHEMA_SUMMARY_BYTES:
        if summary.get("keys"):
            summary["keys"] = summary["keys"][: len(summary["keys"]) // 2]
            summary["keys_truncated"] = True
        else:  # pragma: no cover - defensive
            summary = {"container": summary["container"]}
            break
    return summary


# ─────────────────────────────────────────────────────────────
# Snapshot capture
# ─────────────────────────────────────────────────────────────


def _unverifiable(
    kind: ArtifactKind,
    reason: str,
    account: ByteAccount,
    *,
    shape: Optional[Tuple[int, ...]] = None,
    schema_summary: Optional[Dict[str, Any]] = None,
    fingerprint: Optional[str] = None,
) -> ContentSnapshot:
    """Build an explicitly unverifiable outcome.

    Args:
        kind: Detected evidence type.
        reason: Why the value cannot carry an integrity claim.
        account: Byte accounting.
        shape: Captured shape, when known.
        schema_summary: Structural description, when available.
        fingerprint: A digest that *was* computable but does not prove
            integrity. Retained for diagnostics only; ``evidence_
            verifiable`` stays ``False``.

    Returns:
        The snapshot outcome. ``payload`` is always ``None``: a refusal
        never retains bytes.
    """
    return ContentSnapshot(
        kind=kind,
        outcome=SnapshotOutcome.UNVERIFIABLE,
        payload=None,
        fingerprint=fingerprint,
        fingerprint_algorithm=FINGERPRINT_ALGORITHM if fingerprint else None,
        evidence_verifiable=False,
        account=account,
        shape=shape,
        schema_summary=schema_summary,
        reason=reason,
    )


def _capture_dataframe(df: pd.DataFrame, max_bytes: int) -> ContentSnapshot:
    """Capture a DataFrame snapshot under the byte cap.

    Args:
        df: The frame offered as evidence.
        max_bytes: RAM snapshot cap.

    Returns:
        The outcome.
    """
    shape: Tuple[int, ...] = (int(df.shape[0]), int(df.shape[1]))
    summary = dataframe_schema_summary(df)

    # Nested mutable cells are checked FIRST: they are disqualifying no
    # matter how small the frame is, and no copy should be made for a
    # value that can never be evidence.
    unsafe = unsafe_object_columns(df)
    if unsafe:
        estimate = int(df.memory_usage(deep=True).sum())
        return _unverifiable(
            ArtifactKind.DATAFRAME,
            (
                f"columns {list(unsafe)} hold mutable or non-canonical objects; "
                "deep copy does not detach them and pandas hashes them by repr, "
                "so no fingerprint over this frame proves content integrity"
            ),
            ByteAccount(live_bytes=estimate, snapshot_bytes=0, method=SizeMethod.PANDAS_DEEP_ESTIMATE),
            shape=shape,
            schema_summary=summary,
        )

    # Estimate BEFORE copying: an over-cap frame must never be duplicated
    # in memory just to discover it was too big.
    estimate = int(df.memory_usage(deep=True).sum())
    if estimate > max_bytes:
        return ContentSnapshot(
            kind=ArtifactKind.DATAFRAME,
            outcome=SnapshotOutcome.SPILL_REQUIRED,
            payload=None,
            fingerprint=None,
            fingerprint_algorithm=None,
            evidence_verifiable=False,
            account=ByteAccount(live_bytes=estimate, snapshot_bytes=0, method=SizeMethod.PANDAS_DEEP_ESTIMATE),
            shape=shape,
            schema_summary=summary,
            reason=(
                f"estimated {estimate} bytes exceeds the {max_bytes}-byte RAM snapshot cap; "
                "requires the durable tier, and is unverifiable without one"
            ),
        )

    snapshot = df.copy(deep=True)
    try:
        fingerprint = fingerprint_dataframe(snapshot)
    except UnsupportedEvidence as exc:
        return _unverifiable(
            ArtifactKind.DATAFRAME,
            str(exc),
            ByteAccount(live_bytes=estimate, snapshot_bytes=0, method=SizeMethod.PANDAS_DEEP_ESTIMATE),
            shape=shape,
            schema_summary=summary,
        )

    snapshot_bytes = int(snapshot.memory_usage(deep=True).sum())
    return ContentSnapshot(
        kind=ArtifactKind.DATAFRAME,
        outcome=SnapshotOutcome.CAPTURED,
        payload=snapshot,
        fingerprint=fingerprint,
        fingerprint_algorithm=FINGERPRINT_ALGORITHM,
        evidence_verifiable=True,
        account=ByteAccount(live_bytes=estimate, snapshot_bytes=snapshot_bytes, method=SizeMethod.PANDAS_DEEP_ESTIMATE),
        shape=shape,
        schema_summary=summary,
        reason=None,
    )


def _capture_text(value: str, max_bytes: int) -> ContentSnapshot:
    """Capture a text snapshot under the byte cap.

    Args:
        value: The text offered as evidence.
        max_bytes: RAM snapshot cap.

    Returns:
        The outcome.
    """
    shape: Tuple[int, ...] = (len(value),)

    # UTF-8 uses at least one byte per character, so a string longer than
    # the cap is certainly over it. Checking that first avoids encoding a
    # huge string only to throw the buffer away.
    if len(value) > max_bytes:
        return ContentSnapshot(
            kind=ArtifactKind.TEXT,
            outcome=SnapshotOutcome.SPILL_REQUIRED,
            payload=None,
            fingerprint=None,
            fingerprint_algorithm=None,
            evidence_verifiable=False,
            account=ByteAccount(live_bytes=None, snapshot_bytes=0, method=SizeMethod.CANONICAL_UTF8),
            shape=shape,
            schema_summary={"encoding": "utf-8", "char_count": len(value)},
            reason=(
                f"{len(value)} characters exceeds the {max_bytes}-byte cap before encoding; "
                "requires the durable tier"
            ),
        )

    encoded = value.encode("utf-8")
    summary = {"encoding": "utf-8", "char_count": len(value), "byte_count": len(encoded)}
    if len(encoded) > max_bytes:
        return ContentSnapshot(
            kind=ArtifactKind.TEXT,
            outcome=SnapshotOutcome.SPILL_REQUIRED,
            payload=None,
            fingerprint=None,
            fingerprint_algorithm=None,
            evidence_verifiable=False,
            account=ByteAccount(live_bytes=len(encoded), snapshot_bytes=0, method=SizeMethod.CANONICAL_UTF8),
            shape=shape,
            schema_summary=summary,
            reason=(f"{len(encoded)} encoded bytes exceeds the {max_bytes}-byte cap; requires the durable tier"),
        )

    # ``str`` is immutable, so the value is its own detached snapshot.
    return ContentSnapshot(
        kind=ArtifactKind.TEXT,
        outcome=SnapshotOutcome.CAPTURED,
        payload=value,
        fingerprint=fingerprint_bytes(encoded),
        fingerprint_algorithm=FINGERPRINT_ALGORITHM,
        evidence_verifiable=True,
        account=ByteAccount(live_bytes=len(encoded), snapshot_bytes=len(encoded), method=SizeMethod.CANONICAL_UTF8),
        shape=shape,
        schema_summary=summary,
        reason=None,
    )


def _capture_json(value: Any, max_bytes: int) -> ContentSnapshot:
    """Capture a JSON snapshot under the byte cap.

    The snapshot is produced by decoding the canonical encoding, not by
    ``copy.deepcopy``: a round trip through canonical bytes is provably
    detached from the caller's object graph and normalizes key order at
    the same time.

    Args:
        value: The ``dict`` or ``list`` offered as evidence.
        max_bytes: RAM snapshot cap.

    Returns:
        The outcome.
    """
    summary = _json_schema_summary(value)
    shape: Tuple[int, ...] = (len(value),)

    try:
        encoded = canonical_json_bytes(value)
    except UnsupportedEvidence as exc:
        return _unverifiable(
            ArtifactKind.JSON,
            str(exc),
            ByteAccount(live_bytes=None, snapshot_bytes=0, method=SizeMethod.UNKNOWN),
            shape=shape,
            schema_summary=summary,
        )

    if len(encoded) > max_bytes:
        # The transient encode buffer is released here; the decoded
        # snapshot — the copy that would actually be retained — is never
        # materialized.
        return ContentSnapshot(
            kind=ArtifactKind.JSON,
            outcome=SnapshotOutcome.SPILL_REQUIRED,
            payload=None,
            fingerprint=None,
            fingerprint_algorithm=None,
            evidence_verifiable=False,
            account=ByteAccount(live_bytes=len(encoded), snapshot_bytes=0, method=SizeMethod.CANONICAL_UTF8),
            shape=shape,
            schema_summary=summary,
            reason=(f"{len(encoded)} canonical bytes exceeds the {max_bytes}-byte cap; requires the durable tier"),
        )

    return ContentSnapshot(
        kind=ArtifactKind.JSON,
        outcome=SnapshotOutcome.CAPTURED,
        payload=orjson.loads(encoded),
        fingerprint=fingerprint_bytes(encoded),
        fingerprint_algorithm=FINGERPRINT_ALGORITHM,
        evidence_verifiable=True,
        account=ByteAccount(live_bytes=len(encoded), snapshot_bytes=len(encoded), method=SizeMethod.CANONICAL_UTF8),
        shape=shape,
        schema_summary=summary,
        reason=None,
    )


def _capture_binary(value: Any, max_bytes: int) -> ContentSnapshot:
    """Account for a binary value, which is never verifiable evidence.

    Bytes have a perfectly good checksum, but :data:`ArtifactKind.BINARY`
    is not supported evidence: there is no canonical *content* model for
    it, so a digest cannot support a completion claim.

    Args:
        value: The binary value.
        max_bytes: RAM snapshot cap.

    Returns:
        An unverifiable outcome carrying honest byte accounting.
    """
    data = bytes(value)
    return _unverifiable(
        ArtifactKind.BINARY,
        "binary values have no canonical content model and cannot carry verifiable evidence",
        ByteAccount(live_bytes=len(data), snapshot_bytes=0, method=SizeMethod.RAW_BYTES),
        shape=(len(data),),
        schema_summary={"byte_count": len(data), "checksum": blob_checksum(data)},
    )


def capture_snapshot(
    value: Any,
    *,
    max_bytes: int,
    kind: Optional[ArtifactKind] = None,
) -> ContentSnapshot:
    """Snapshot, fingerprint and account for a value offered as evidence.

    Never raises for an unsupported value: an unsupported or oversized
    value is a *result* the caller must record honestly, not an error.
    The only exception is an invalid ``max_bytes``, which is a caller bug.

    This is CPU-bound for large inputs — measured at ~9.5 s to fingerprint
    a 256 MiB numeric frame. Call :func:`capture_snapshot_async` from an
    event loop, and never hold a lock across either form.

    Args:
        value: The value to snapshot.
        max_bytes: RAM snapshot cap in bytes. ``0`` means never retain a
            RAM snapshot, so every supported value reports
            :data:`SnapshotOutcome.SPILL_REQUIRED`.
        kind: Force an evidence type instead of detecting one. A forced
            kind that does not match the value falls through to the
            unverifiable path rather than being trusted.

    Returns:
        The :class:`ContentSnapshot` outcome.

    Raises:
        ValueError: If ``max_bytes`` is negative.
    """
    if max_bytes < 0:
        raise ValueError(f"max_bytes must be >= 0, got {max_bytes}")

    detected = detect_kind(value)
    effective = kind or detected
    if kind is not None and kind is not detected:
        return _unverifiable(
            kind,
            f"declared kind {kind.value!r} does not match the value's actual type {detected.value!r}",
            ByteAccount(live_bytes=None, snapshot_bytes=0, method=SizeMethod.UNKNOWN),
        )

    if effective is ArtifactKind.DATAFRAME:
        return _capture_dataframe(value, max_bytes)
    if effective is ArtifactKind.TEXT:
        return _capture_text(value, max_bytes)
    if effective is ArtifactKind.JSON:
        return _capture_json(value, max_bytes)
    if effective is ArtifactKind.BINARY:
        return _capture_binary(value, max_bytes)

    # ArtifactKind.OBJECT. `sys.getsizeof` would report only the shallow
    # container and never prove the object fits, so the footprint is
    # reported as genuinely unknown instead of guessed.
    return _unverifiable(
        ArtifactKind.OBJECT,
        (
            f"{type(value).__name__} is not a supported evidence type; its size cannot be "
            "established and no canonical fingerprint exists for it"
        ),
        ByteAccount(live_bytes=None, snapshot_bytes=0, method=SizeMethod.UNKNOWN),
    )


async def capture_snapshot_async(
    value: Any,
    *,
    max_bytes: int,
    kind: Optional[ArtifactKind] = None,
) -> ContentSnapshot:
    """Await :func:`capture_snapshot` on a worker thread.

    Copying and hashing are CPU-bound and dominate registration cost, so
    they must not run on the event loop. This function is pure with
    respect to shared state — it mutates no catalog and no cache — which
    is what makes running it off-thread safe. The caller commits the
    result on the owning loop, and must not hold the catalog lock while
    awaiting this.

    Args:
        value: The value to snapshot.
        max_bytes: RAM snapshot cap in bytes.
        kind: Force an evidence type instead of detecting one.

    Returns:
        The :class:`ContentSnapshot` outcome.

    Raises:
        ValueError: If ``max_bytes`` is negative.
    """
    return await asyncio.to_thread(capture_snapshot, value, max_bytes=max_bytes, kind=kind)
