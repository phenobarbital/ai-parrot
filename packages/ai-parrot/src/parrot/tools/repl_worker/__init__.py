"""Persistent-worker sandbox for ``PythonREPLTool`` (FEAT-380 Sandbox Hardening).

This package holds the control protocol (``protocol.py``), the worker
process entrypoint (``worker.py``), and the host-side lifecycle classes
(``WorkerHandle``, ``WorkerPool``) that let ``PythonREPLTool`` run
LLM-generated code in a spawned, resource-limited child process instead of
in-process via ``exec()``/``eval()`` on the server's own thread pool.

``PythonREPLTool`` (TASK-1943) imports ``WorkerPool``/``WorkerPoolExhaustedError``
from here to acquire its per-instance persistent worker lazily on first use.
Arrow DataFrame transport (``inject_dataframe``) lands in TASK-1945.
"""

from .handle import NamespaceTimeoutError, WorkerBootstrapError, WorkerHandle
from .inprocess import InProcessHandle
from .pool import WorkerPool, WorkerPoolExhaustedError
from .protocol import (
    ErrorResponse,
    ExecRequest,
    ExecResult,
    GetVarRequest,
    InjectDfRequest,
    ListNsRequest,
    ListNsResponse,
    MemoryVerdict,
    NamespaceLossError,
    OkResponse,
    PingRequest,
    PongResponse,
    ProcessSample,
    ReadyResponse,
    ResetRequest,
    SetVarRequest,
    SnapshotRequest,
    SnapshotResponse,
    ValueResponse,
    Verdict,
    WorkerConfig,
    decode_value,
    encode_value,
    read_frame,
    write_frame,
)

__all__ = [
    "ErrorResponse",
    "ExecRequest",
    "ExecResult",
    "GetVarRequest",
    "InjectDfRequest",
    "ListNsRequest",
    "ListNsResponse",
    "MemoryVerdict",
    "NamespaceLossError",
    "NamespaceTimeoutError",
    "OkResponse",
    "PingRequest",
    "PongResponse",
    "ProcessSample",
    "ReadyResponse",
    "ResetRequest",
    "SetVarRequest",
    "SnapshotRequest",
    "SnapshotResponse",
    "ValueResponse",
    "Verdict",
    "WorkerBootstrapError",
    "WorkerConfig",
    "WorkerHandle",
    "InProcessHandle",
    "WorkerPool",
    "WorkerPoolExhaustedError",
    "decode_value",
    "encode_value",
    "read_frame",
    "write_frame",
]
