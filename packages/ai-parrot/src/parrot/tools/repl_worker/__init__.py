"""Persistent-worker sandbox for ``PythonREPLTool`` (FEAT-380 Sandbox Hardening).

This package holds the control protocol (``protocol.py``) and the worker
process entrypoint (``worker.py``) that let ``PythonREPLTool`` run
LLM-generated code in a spawned, resource-limited child process instead of
in-process via ``exec()``/``eval()`` on the server's own thread pool.

Host-side pieces (``WorkerHandle``, ``WorkerPool``, Arrow DataFrame
transport) are added by later tasks in this feature (TASK-1941/1942/1945).
"""

from .protocol import (
    ErrorResponse,
    ExecRequest,
    ExecResult,
    GetVarRequest,
    InjectDfRequest,
    ListNsRequest,
    ListNsResponse,
    NamespaceLossError,
    OkResponse,
    PingRequest,
    PongResponse,
    ResetRequest,
    SetVarRequest,
    SnapshotRequest,
    SnapshotResponse,
    ValueResponse,
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
    "NamespaceLossError",
    "OkResponse",
    "PingRequest",
    "PongResponse",
    "ResetRequest",
    "SetVarRequest",
    "SnapshotRequest",
    "SnapshotResponse",
    "ValueResponse",
    "WorkerConfig",
    "decode_value",
    "encode_value",
    "read_frame",
    "write_frame",
]
