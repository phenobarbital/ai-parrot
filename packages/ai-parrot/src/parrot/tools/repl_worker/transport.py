"""DataFrame transport: Arrow IPC over shared memory (FEAT-380 Module 7 / G9).

DataFrames cross the host -> worker boundary without an expensive copy:
Arrow IPC over a ``multiprocessing.shared_memory`` block is the primary
path; pickle+base64 is the fallback **only** for dtypes Arrow cannot
represent, and that fallback always logs a warning (mandatory, not
optional — spec G9: "pickle solo como fallback con warning").

Shared-memory ownership (documented, per the task's Key Constraint — "leaked
shm segments fail CI"):

- The **host** creates the block, writes the Arrow IPC stream, and sends its
  name (never the worker).
- The **worker** opens the block, decodes it, and ``close()``s its handle —
  it never ``unlink()``s (see ``worker.py``'s dispatch).
- The **host** ``unlink()``s the block only after receiving the worker's ACK
  (the framed response to the ``inject_df`` request) — see
  ``handle.py::WorkerHandle.inject_dataframe`` — guaranteeing the worker has
  already finished reading before the block is freed.

Zero-copy applies only where Arrow/pandas dtype conversion is compatible
(e.g. plain numeric/string columns); object columns holding non-Arrow types
still copy during ``to_pandas()``/``from_pandas()``. This module never
claims otherwise in logs or docs.
"""

from __future__ import annotations

import base64
import logging
import pickle
from multiprocessing import shared_memory
from typing import Any, NamedTuple, Optional

import pandas as pd
import pyarrow as pa

logger = logging.getLogger(__name__)

#: pyarrow exceptions that mean "this dtype/value can't round-trip through
#: Arrow" — the ONLY triggers for the pickle fallback (Key Constraint: catch
#: those specifically, never a blind `Exception`).
_ARROW_CONVERSION_ERRORS = (pa.lib.ArrowInvalid, pa.lib.ArrowNotImplementedError, pa.lib.ArrowTypeError)


class StrictTransportError(Exception):
    """A value cannot cross the worker boundary under strict evidence rules.

    Raised **before** any pickle payload is constructed (FEAT-538 §2 "REPL
    Recovery"). Task-memory evidence must never travel as pickle: the
    point of a strict load is that what arrives in the worker is provably
    the artifact that was fingerprinted, and an arbitrary pickle payload
    proves nothing about its own contents.

    This is deliberately *not* a subclass of the Arrow errors: a caller
    catching Arrow-conversion failures to fall back to pickle must not
    accidentally swallow a strict refusal.
    """


#: Types a strict JSON value may contain. Anything else — a DataFrame, a
#: custom object, a callable, a set, bytes — is refused rather than
#: pickled. ``tuple`` is excluded on purpose: it round-trips as a list,
#: so accepting it would mean the value that arrives is not the value
#: that was sent.
_STRICT_JSON_SCALARS = (bool, int, float, str, type(None))

#: Default ceiling for one strict transfer. Mirrors the task-memory
#: rehydration ceiling so a strict load cannot smuggle a larger payload
#: across the process boundary than a raw read would have allowed.
DEFAULT_STRICT_MAX_BYTES: int = 2_000_000


class EncodedDataFrame(NamedTuple):
    """Wire-ready encoding of one DataFrame, produced by :func:`encode_dataframe`."""

    format: str  # "arrow" | "pickle"
    shm_name: Optional[str]
    size: Optional[int]
    payload: Optional[str]  # base64 pickle bytes, format == "pickle" only


def encode_dataframe(
    df: pd.DataFrame,
    name: str,
    *,
    strict: bool = False,
    max_bytes: Optional[int] = None,
) -> EncodedDataFrame:
    """Serialize ``df`` for host -> worker transport.

    Tries Arrow IPC into a brand-new ``SharedMemory`` block first; falls
    back to pickle+base64 (logged) when ``pyarrow`` cannot represent a
    column's dtype.

    Args:
        df: The DataFrame to encode.
        name: Variable name it will be bound to — used only for the
            fallback warning message.
        strict: Opt-in strict evidence mode (FEAT-538). When ``True``, an
            Arrow conversion failure raises :class:`StrictTransportError`
            **before** any pickle payload is constructed, and the encoded
            size is checked against ``max_bytes``. Defaults to ``False``,
            which preserves the legacy behaviour byte for byte.
        max_bytes: Ceiling for the encoded Arrow stream. Only consulted in
            strict mode; ``None`` uses :data:`DEFAULT_STRICT_MAX_BYTES`.

    Returns:
        An :class:`EncodedDataFrame` describing what to put on the wire.
        The caller (``WorkerHandle.inject_dataframe``) owns unlinking the
        shm block once the worker has ack'd (see module docstring).

    Raises:
        StrictTransportError: In strict mode only — when Arrow cannot
            represent a column, or the encoded stream exceeds
            ``max_bytes``. No shared-memory block is left behind in
            either case.
    """
    try:
        table = pa.Table.from_pandas(df, preserve_index=True)
    except _ARROW_CONVERSION_ERRORS as exc:
        if strict:
            # The refusal happens HERE, before `pickle.dumps` is even
            # reached. Creating the payload and then declining to send it
            # would still have serialized arbitrary objects in-process.
            raise StrictTransportError(
                f"DataFrame {name!r} cannot be transported as task-memory evidence: "
                f"Arrow conversion failed ({exc}). Strict mode never falls back to pickle."
            ) from exc
        logger.warning(
            "DataFrame %r fell back to pickle transport (Arrow conversion failed " "for one or more columns): %s",
            name,
            exc,
        )
        payload = base64.b64encode(pickle.dumps(df)).decode("ascii")
        return EncodedDataFrame(format="pickle", shm_name=None, size=None, payload=payload)

    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    buf = sink.getvalue()
    size = buf.size

    if strict:
        ceiling = DEFAULT_STRICT_MAX_BYTES if max_bytes is None else max_bytes
        if size > ceiling:
            # Refused before the shm block is created, so an over-size
            # transfer leaks nothing.
            raise StrictTransportError(
                f"DataFrame {name!r} encodes to {size} bytes, above the strict ceiling of {ceiling}"
            )

    shm = shared_memory.SharedMemory(create=True, size=max(size, 1))
    try:
        shm.buf[:size] = buf.to_pybytes()
    except BaseException:
        # Any failure while filling the block must not strand it: the host
        # owns the segment from the moment it is created, and nothing
        # downstream has learned its name yet.
        shm.close()
        unlink_shm(shm.name)
        raise
    else:
        # Host keeps ownership of the block (it created it) — closing here
        # only detaches THIS process's local mapping, it does NOT unlink.
        shm.close()
    return EncodedDataFrame(format="arrow", shm_name=shm.name, size=size, payload=None)


def validate_strict_dataframe(df: pd.DataFrame, name: str, *, max_bytes: Optional[int] = None) -> None:
    """Check that ``df`` *would* be acceptable strict evidence, without sending it.

    Used by the in-process adapter, which binds a DataFrame by plain
    assignment and so never serializes anything. Running the identical
    check there is what stops the in-process mode from being silently more
    permissive than the subprocess one — a frame a real worker would
    refuse as unverifiable evidence must not quietly succeed just because
    no process boundary happened to be involved.

    Args:
        df: The DataFrame to validate.
        name: Variable name, for the error message.
        max_bytes: Ceiling for the encoded Arrow stream. ``None`` uses
            :data:`DEFAULT_STRICT_MAX_BYTES`.

    Raises:
        StrictTransportError: If Arrow cannot represent the frame, or the
            encoded stream would exceed ``max_bytes``.
    """
    try:
        table = pa.Table.from_pandas(df, preserve_index=True)
    except _ARROW_CONVERSION_ERRORS as exc:
        raise StrictTransportError(
            f"DataFrame {name!r} cannot be used as task-memory evidence: "
            f"Arrow conversion failed ({exc}). Strict mode never falls back to pickle."
        ) from exc

    ceiling = DEFAULT_STRICT_MAX_BYTES if max_bytes is None else max_bytes
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    size = sink.getvalue().size
    if size > ceiling:
        raise StrictTransportError(f"DataFrame {name!r} encodes to {size} bytes, above the strict ceiling of {ceiling}")


def ensure_strict_json(value: Any, *, name: str, max_bytes: Optional[int] = None, _depth: int = 0) -> Any:
    """Validate that ``value`` is safe JSON evidence, or refuse it.

    Strict evidence values travel as plain JSON, never as pickle. Only
    ``None``/``bool``/``int``/``float``/``str`` and ``list``/``dict``
    composed of them are permitted. ``tuple`` is refused even though it
    looks JSON-safe: it round-trips as a ``list``, so accepting one would
    mean the value that arrives is not the value that was sent — and for
    evidence, that is the whole question.

    Args:
        value: The value to validate.
        name: Variable name, for the error message.
        max_bytes: Ceiling for the canonical encoding. ``None`` uses
            :data:`DEFAULT_STRICT_MAX_BYTES`.
        _depth: Internal recursion depth guard.

    Returns:
        ``value`` unchanged, when it is acceptable.

    Raises:
        StrictTransportError: If the value contains an unsupported type, a
            non-string mapping key, exceeds the depth guard, or exceeds
            ``max_bytes`` once encoded.
    """
    if _depth > 32:
        raise StrictTransportError(f"value {name!r} nests deeper than the strict transport allows")

    if isinstance(value, _STRICT_JSON_SCALARS):
        pass
    elif isinstance(value, list):
        for item in value:
            ensure_strict_json(item, name=name, max_bytes=max_bytes, _depth=_depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise StrictTransportError(
                    f"value {name!r} has a non-string mapping key ({type(key).__name__}); "
                    "strict JSON evidence must round-trip exactly"
                )
            ensure_strict_json(item, name=name, max_bytes=max_bytes, _depth=_depth + 1)
    else:
        raise StrictTransportError(
            f"value {name!r} of type {type(value).__name__} is not supported strict evidence; "
            "strict mode never creates a pickle payload"
        )

    if _depth == 0:
        import json

        ceiling = DEFAULT_STRICT_MAX_BYTES if max_bytes is None else max_bytes
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > ceiling:
            raise StrictTransportError(
                f"value {name!r} encodes to {len(encoded)} bytes, above the strict ceiling of {ceiling}"
            )
    return value


def decode_dataframe_from_shm(shm_name: str, size: int) -> pd.DataFrame:
    """Worker side: read a DataFrame back from an Arrow IPC shared-memory block.

    Args:
        shm_name: Name of the shared-memory block the host created.
        size: Exact byte length of the IPC stream within the block.

    Returns:
        The decoded DataFrame.
    """
    shm = shared_memory.SharedMemory(name=shm_name)
    try:
        data = bytes(shm.buf[:size])
    finally:
        # Worker never unlinks — the host owns the block's lifecycle and
        # unlinks it after this call returns (its ACK reaches the host).
        shm.close()
    reader = pa.ipc.open_stream(data)
    table = reader.read_all()
    return table.to_pandas()


def decode_pickle_payload(payload: str) -> pd.DataFrame:
    """Worker side: decode the pickle fallback payload.

    Args:
        payload: Base64-encoded pickle bytes produced by :func:`encode_dataframe`.

    Returns:
        The decoded DataFrame.
    """
    return pickle.loads(base64.b64decode(payload))


def unlink_shm(shm_name: str) -> None:
    """Host side: free a shared-memory block after the worker has ack'd.

    Best-effort — a block that's already gone (e.g. a retried cleanup) is
    not an error.

    Args:
        shm_name: Name of the block to free.
    """
    try:
        shm = shared_memory.SharedMemory(name=shm_name)
    except FileNotFoundError:
        return
    try:
        shm.close()
        shm.unlink()
    except FileNotFoundError:
        pass
