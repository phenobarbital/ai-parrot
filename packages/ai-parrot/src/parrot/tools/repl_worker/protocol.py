"""Control protocol for the persistent REPL worker (FEAT-380 Module 2).

Length-prefixed Pydantic messages exchanged between the host
(``PythonREPLTool`` / ``WorkerHandle``, TASK-1941+) and the persistent REPL
worker process spawned by ``worker.py``. One message per request/response,
framed as a 4-byte big-endian unsigned length prefix followed by the
message's JSON payload (spec Sandbox Hardening §2 "Control Protocol").

Values that are not natively JSON-serializable (e.g. a DataFrame passed to
``set_var``) are wrapped with :func:`encode_value` / :func:`decode_value` —
a pickle+base64 fallback, the same "works for everything, fast for nothing"
posture the spec calls for on the DataFrame transport (G9). Zero-copy Arrow
IPC / shared-memory transport for DataFrames is TASK-1945; this task only
guarantees *some* value makes it across the wire for `get_var`/`set_var`/
`snapshot`.
"""

from __future__ import annotations

import base64
import io as _io
import json
import pickle
import struct
import types
from typing import Any, BinaryIO, Literal, Optional

from pydantic import BaseModel, Field

# 4-byte, big-endian, unsigned length prefix — never newline-delimited JSON,
# since REPL output frequently embeds newlines (Key Constraint).
_LENGTH_STRUCT = struct.Struct(">I")

#: Sentinel key identifying a pickle+base64-wrapped value inside a JSON payload.
_PICKLE_MARKER = "__repl_worker_pickle_b64__"

# ---------------------------------------------------------------------------
# Insecure-deserialization guard (code-review finding, post-TASK-1945)
# ---------------------------------------------------------------------------
#
# `decode_value()` runs on the HOST for `get_var()`/`snapshot()` responses —
# i.e. on data whose SHAPE (not just contents) is influenced by whatever the
# LLM's sandboxed code put in the namespace. `encode_value()`'s dict branch
# preserves dict KEYS verbatim, so a plain, JSON-native dict literal typed
# directly in sandboxed code —
#
#     x = {"__repl_worker_pickle_b64__": "<payload computed offline>"}
#
# — is indistinguishable, by shape alone, from a value `encode_value()`
# itself pickled. No `import pickle`/`import base64` inside the sandbox is
# needed: the payload is a plain string literal, so the AST/allowlist gate
# sees nothing but an ordinary dict-of-strings. Without a restriction here,
# `pickle.loads()` on that payload gives arbitrary code execution in the
# UNSANDBOXED HOST process — a full breach of the process-isolation boundary
# this whole feature exists to build (the same class of bug the codebase
# already denylists `pd.read_pickle`/`to_pickle` for, reopened through an
# ungated door).
#
# Mitigation: restrict `Unpickler.find_class()` to a data-only allowlist
# (pandas/numpy/datetime/decimal/collections/plain builtins), rejecting
# dangerous builtins explicitly. Most `__reduce__`-based RCE gadgets
# (`os.system`, `subprocess.Popen`, `builtins.eval`, `functools.partial`
# wrapping a dangerous callable, ...) resolve to a module outside this
# allowlist and fail closed in `find_class()` before ever being called —
# unpickling a value shaped like a DataFrame/ndarray/plain container still
# works; unpickling a `__reduce__` payload that would call an arbitrary
# executable does not.
_SAFE_PICKLE_TOP_LEVEL_MODULES = frozenset(
    {
        "pandas", "numpy", "datetime", "decimal", "collections", "builtins",
        # `pathlib` round-trips plain path data only (no `__reduce__` gadget
        # comparable to os/subprocess) and legitimately shows up in the REPL
        # namespace, e.g. `report_directory` (code-review fix, discovered via
        # `snapshot()` on a freshly-bootstrapped worker).
        "pathlib",
    }
)
#: Builtins that ARE data-only-module members but are dangerous as callables
#: if a `__reduce__` payload resolves to them (e.g. `(eval, ("...",))`).
_UNSAFE_BUILTINS = frozenset(
    {
        "eval", "exec", "compile", "__import__", "open", "input",
        "breakpoint", "getattr", "setattr", "delattr", "vars", "globals",
        "locals", "memoryview",
    }
)


class _RestrictedUnpickler(pickle.Unpickler):
    """Unpickler that only resolves classes/functions under a safe allowlist.

    See the module-level comment above for the threat this defends against.
    """

    def find_class(self, module: str, name: str) -> Any:  # noqa: D102 - see class docstring
        top_level = module.split(".", 1)[0]
        if top_level not in _SAFE_PICKLE_TOP_LEVEL_MODULES:
            raise pickle.UnpicklingError(
                f"repl_worker: refusing to unpickle {module}.{name} "
                "(insecure-deserialization guard — module not on the allowlist)"
            )
        if module == "builtins" and name in _UNSAFE_BUILTINS:
            raise pickle.UnpicklingError(
                f"repl_worker: refusing to unpickle builtins.{name} "
                "(insecure-deserialization guard — dangerous builtin)"
            )
        return super().find_class(module, name)


def _safe_pickle_loads(data: bytes) -> Any:
    """``pickle.loads()`` guarded by :class:`_RestrictedUnpickler`.

    Args:
        data: Raw pickle bytes (already base64-decoded).

    Returns:
        The unpickled value.

    Raises:
        pickle.UnpicklingError: ``data`` tries to reconstruct a class/
            function outside the safe allowlist.
    """
    return _RestrictedUnpickler(_io.BytesIO(data)).load()


def encode_value(value: Any) -> Any:
    """Best-effort JSON-safe encoding for one namespace value.

    Native JSON types (``None``/``bool``/``int``/``float``/``str`` and
    ``list``/``dict`` composed of them) pass through unchanged. Anything
    else (DataFrames, custom objects, …) is pickled and base64-wrapped so it
    can still travel inside the JSON frame.

    Args:
        value: The namespace value to encode.

    Returns:
        A JSON-serializable representation of ``value``.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [encode_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): encode_value(v) for k, v in value.items()}
    if isinstance(value, types.ModuleType) or callable(value):
        # Code-review fix: modules/functions/callables are never meaningful
        # "data" to hand back across the wire, and pickling one means the
        # host's restricted unpickler (see `_RestrictedUnpickler` above)
        # would need to reconstruct an arbitrary callable reference — the
        # exact thing that guard exists to refuse. This can be reached not
        # just for a namespace value itself (already filtered a layer up by
        # `WorkerNamespace.snapshot()`) but for a callable *nested inside* an
        # otherwise-plain container (e.g. a dict of helper functions), so the
        # check lives here, applied recursively. Represent it as an inert
        # placeholder instead of ever attempting to pickle it.
        label = getattr(value, "__qualname__", None) or getattr(value, "__name__", None) or repr(value)
        return f"<{type(value).__name__}: {label} (not transportable)>"
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return {_PICKLE_MARKER: base64.b64encode(pickle.dumps(value)).decode("ascii")}


def decode_value(value: Any) -> Any:
    """Inverse of :func:`encode_value`.

    Args:
        value: A JSON-safe value previously produced by :func:`encode_value`.

    Returns:
        The original Python value (unpickled if it was pickle-wrapped).
    """
    if isinstance(value, dict) and set(value) == {_PICKLE_MARKER}:
        return _safe_pickle_loads(base64.b64decode(value[_PICKLE_MARKER]))
    if isinstance(value, dict):
        return {k: decode_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode_value(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Host -> worker requests
# ---------------------------------------------------------------------------


class ExecRequest(BaseModel):
    """Host -> worker: execute code under a deadline."""

    op: Literal["exec"] = "exec"
    code: str
    debug: bool = False
    deadline_ms: int = Field(..., gt=0)


class InjectDfRequest(BaseModel):
    """Host -> worker: inject a DataFrame into the namespace.

    Implemented by TASK-1945: Arrow IPC over shared memory as the primary
    transport (``format="arrow"``), pickle+base64 as the fallback
    (``format="pickle"``) for dtypes Arrow cannot represent (spec G9).
    """

    op: Literal["inject_df"] = "inject_df"
    name: str
    format: Literal["arrow", "pickle"] = "arrow"
    #: shared-memory block name carrying the Arrow IPC stream (format="arrow").
    shm_name: Optional[str] = None
    #: exact byte length written into the shm block (format="arrow").
    size: Optional[int] = None
    #: base64-encoded pickle bytes (format="pickle").
    payload: Optional[str] = None


class GetVarRequest(BaseModel):
    """Host -> worker: read one namespace variable (namespace API)."""

    op: Literal["get_var"] = "get_var"
    name: str


class SetVarRequest(BaseModel):
    """Host -> worker: write one namespace variable (namespace API)."""

    op: Literal["set_var"] = "set_var"
    name: str
    value: Any = None


class ListNsRequest(BaseModel):
    """Host -> worker: cheap, name-only namespace listing (host name-shadow feed)."""

    op: Literal["list_ns"] = "list_ns"


class SnapshotRequest(BaseModel):
    """Host -> worker: serializable dump of the whole namespace."""

    op: Literal["snapshot"] = "snapshot"


class ResetRequest(BaseModel):
    """Host -> worker: reset the REPL environment (equivalent to ``reset_environment()``)."""

    op: Literal["reset"] = "reset"


class PingRequest(BaseModel):
    """Host -> worker: health check."""

    op: Literal["ping"] = "ping"


# ---------------------------------------------------------------------------
# Worker -> host responses
# ---------------------------------------------------------------------------


class ExecResult(BaseModel):
    """Worker -> host: mirrors today's ``_execute()`` contract (G5)."""

    op: Literal["result"] = "result"
    output: str | None = None  # success path (str)
    status: str | None = None  # "error" | "done_with_errors"
    result: Any | None = None
    error: str | None = None
    new_vars: list[str] = Field(default_factory=list)  # feeds host name-shadow


class ValueResponse(BaseModel):
    """Worker -> host: reply to :class:`GetVarRequest`."""

    op: Literal["value"] = "value"
    name: str
    value: Any = None


class OkResponse(BaseModel):
    """Worker -> host: generic acknowledgement (``set_var``, ``reset``)."""

    op: Literal["ok"] = "ok"


class ListNsResponse(BaseModel):
    """Worker -> host: reply to :class:`ListNsRequest`."""

    op: Literal["list_ns_result"] = "list_ns_result"
    names: list[str] = Field(default_factory=list)


class SnapshotResponse(BaseModel):
    """Worker -> host: reply to :class:`SnapshotRequest`."""

    op: Literal["snapshot_result"] = "snapshot_result"
    data: dict[str, Any] = Field(default_factory=dict)


class PongResponse(BaseModel):
    """Worker -> host: reply to :class:`PingRequest`."""

    op: Literal["pong"] = "pong"


class ErrorResponse(BaseModel):
    """Worker -> host: generic error envelope (unknown/unimplemented op, dispatch failure)."""

    op: Literal["error"] = "error"
    message: str


class NamespaceLossError(BaseModel):
    """Payload embedded in the ``{status, result, error}`` dict after a kill.

    Constructed host-side (TASK-1941+ owns deadline/SIGKILL enforcement);
    defined here because it is part of the frozen protocol contract (spec
    §2 Data Models).
    """

    cause: Literal["timeout", "memory", "crash"]
    lost_variables: list[str] = Field(default_factory=list)
    message: str


class WorkerConfig(BaseModel):
    """Deployment-tunable limits (all with working defaults)."""

    # ~12 GiB — empirically calibrated (TASK-1946, Module 8): observed peak
    # VmPeak 5522.8 MB across a full session (bootstrap + 500 MB DataFrame +
    # merge/groupby + plot) x ~2 margin, rounded. See
    # artifacts/logs/feat-380-rlimit-as-calibration.md for the full
    # measurements/method — re-run scripts/sdd/calibrate_rlimit_as.py after
    # any pandas/numpy/matplotlib/pyarrow version bump.
    rlimit_as_bytes: int = 12 * 1024**3
    rlimit_cpu_seconds: int = 300
    rlimit_nofile: int = 256
    deadline_ms: int = 60_000
    max_workers: int = 0  # 0 -> max(4, cpu_count), cap 16
    idle_ttl_seconds: int = 1800  # 30 min
    prewarm_pool_size: int = 2


#: Every concrete message type, keyed by its ``op`` literal — used to parse
#: an incoming frame's JSON payload back into the right Pydantic model.
_MESSAGE_TYPES: dict[str, type[BaseModel]] = {
    "exec": ExecRequest,
    "inject_df": InjectDfRequest,
    "get_var": GetVarRequest,
    "set_var": SetVarRequest,
    "list_ns": ListNsRequest,
    "snapshot": SnapshotRequest,
    "reset": ResetRequest,
    "ping": PingRequest,
    "result": ExecResult,
    "value": ValueResponse,
    "ok": OkResponse,
    "list_ns_result": ListNsResponse,
    "snapshot_result": SnapshotResponse,
    "pong": PongResponse,
    "error": ErrorResponse,
}


def _read_exact(stream: BinaryIO, n: int) -> bytes:
    """Read exactly ``n`` bytes from ``stream``.

    Args:
        stream: Binary stream to read from.
        n: Exact number of bytes required.

    Returns:
        The bytes read.

    Raises:
        EOFError: the stream closed before ``n`` bytes were available.
    """
    chunks: list[bytes] = []
    remaining = n
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            if chunks:
                raise EOFError("repl_worker protocol: stream closed mid-frame")
            raise EOFError("repl_worker protocol: stream closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def write_frame(stream: BinaryIO, message: BaseModel) -> None:
    """Write one length-prefixed protocol message to ``stream``.

    Frame layout: 4-byte big-endian unsigned length, followed by the
    message's JSON payload (the ``op`` field is included, so the reader can
    dispatch without an out-of-band schema).

    Args:
        stream: Binary stream to write to (flushed after writing).
        message: The Pydantic protocol message to send.
    """
    payload = message.model_dump_json().encode("utf-8")
    stream.write(_LENGTH_STRUCT.pack(len(payload)))
    stream.write(payload)
    stream.flush()


def read_frame(stream: BinaryIO) -> BaseModel:
    """Read one length-prefixed protocol message from ``stream``.

    Args:
        stream: Binary stream to read from.

    Returns:
        The parsed Pydantic protocol message.

    Raises:
        EOFError: the stream closed before a full frame was read.
        ValueError: the payload's ``op`` field is not a known message type.
    """
    header = _read_exact(stream, _LENGTH_STRUCT.size)
    (length,) = _LENGTH_STRUCT.unpack(header)
    payload = _read_exact(stream, length)
    raw = json.loads(payload)
    op = raw.get("op")
    model_cls = _MESSAGE_TYPES.get(op)
    if model_cls is None:
        raise ValueError(f"repl_worker protocol: unknown message op {op!r}")
    return model_cls.model_validate(raw)
