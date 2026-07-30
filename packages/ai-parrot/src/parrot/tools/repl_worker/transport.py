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
from typing import NamedTuple, Optional

import pandas as pd
import pyarrow as pa

logger = logging.getLogger(__name__)

#: pyarrow exceptions that mean "this dtype/value can't round-trip through
#: Arrow" — the ONLY triggers for the pickle fallback (Key Constraint: catch
#: those specifically, never a blind `Exception`).
_ARROW_CONVERSION_ERRORS = (pa.lib.ArrowInvalid, pa.lib.ArrowNotImplementedError, pa.lib.ArrowTypeError)


class EncodedDataFrame(NamedTuple):
    """Wire-ready encoding of one DataFrame, produced by :func:`encode_dataframe`."""

    format: str  # "arrow" | "pickle"
    shm_name: Optional[str]
    size: Optional[int]
    payload: Optional[str]  # base64 pickle bytes, format == "pickle" only


def encode_dataframe(df: pd.DataFrame, name: str) -> EncodedDataFrame:
    """Serialize ``df`` for host -> worker transport.

    Tries Arrow IPC into a brand-new ``SharedMemory`` block first; falls
    back to pickle+base64 (logged) when ``pyarrow`` cannot represent a
    column's dtype.

    Args:
        df: The DataFrame to encode.
        name: Variable name it will be bound to — used only for the
            fallback warning message.

    Returns:
        An :class:`EncodedDataFrame` describing what to put on the wire.
        The caller (``WorkerHandle.inject_dataframe``) owns unlinking the
        shm block once the worker has ack'd (see module docstring).
    """
    try:
        table = pa.Table.from_pandas(df, preserve_index=True)
    except _ARROW_CONVERSION_ERRORS as exc:
        logger.warning(
            "DataFrame %r fell back to pickle transport (Arrow conversion failed "
            "for one or more columns): %s",
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

    shm = shared_memory.SharedMemory(create=True, size=max(size, 1))
    try:
        shm.buf[:size] = buf.to_pybytes()
    finally:
        # Host keeps ownership of the block (it created it) — closing here
        # only detaches THIS process's local mapping, it does NOT unlink.
        shm.close()
    return EncodedDataFrame(format="arrow", shm_name=shm.name, size=size, payload=None)


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
