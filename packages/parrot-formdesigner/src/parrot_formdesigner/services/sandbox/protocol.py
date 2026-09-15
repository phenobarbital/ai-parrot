"""Length-prefixed JSON wire protocol for sandbox workers (FEAT-459 / M8).

SandboxContext goes IN to a worker; SandboxOutcome, AbortSignal, or a
BrokerRequest come OUT. Both worker pools (TASK-3169 subprocess,
TASK-3170 gVisor) use this exact framing over their child process's
stdio. Frames exceeding MAX_FRAME_BYTES are REJECTED, never truncated.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from parrot_formdesigner.core.snippets import AbortSignal, SandboxContext, SandboxOutcome

logger = logging.getLogger(__name__)

_LENGTH_HEADER_FORMAT = ">I"  # 4-byte big-endian unsigned int
_LENGTH_HEADER_SIZE = struct.calcsize(_LENGTH_HEADER_FORMAT)

#: Hard cap on a single frame's JSON body, in bytes. A snippet's
#: input/output is form-sized data, not a file upload — 1 MiB is
#: generous headroom, not a target.
MAX_FRAME_BYTES = 1_048_576


class FrameTooLargeError(Exception):
    """Raised when a frame's declared or actual size exceeds MAX_FRAME_BYTES."""


class BrokerRequest(BaseModel):
    """One host-mediated I/O request from a tier 3/4 worker (spec §2 HostBroker).

    Attributes:
        kind: Which allowlist category this request falls under —
            matches BrokerAllowlist's field names (TASK-3161).
        target: The specific host/table/channel/toolkit being requested,
            checked against the manifest's corresponding allowlist tuple.
        args: Request-specific payload (e.g. HTTP method/body for
            "http_hosts", a bound query for "query_tables").
    """

    model_config = ConfigDict(extra="forbid")

    kind: str  # "http_hosts" | "query_tables" | "notifications" | "toolkits"
    target: str
    args: dict[str, Any] = Field(default_factory=dict)


class BrokerResponse(BaseModel):
    """The host broker's answer to a BrokerRequest."""

    model_config = ConfigDict(extra="forbid")

    result: dict[str, Any] = Field(default_factory=dict)
    denied: bool = False
    denial_reason: str | None = None


# A frame body is exactly one of these three shapes, tagged by `type` so
# decode_frame() knows which model to reconstruct.
_FRAME_MODELS: dict[str, type[BaseModel]] = {
    "sandbox_context": SandboxContext,
    "sandbox_outcome": SandboxOutcome,
    "abort_signal": AbortSignal,
    "broker_request": BrokerRequest,
    "broker_response": BrokerResponse,
}


def encode_frame(message: BaseModel) -> bytes:
    """Serialise `message` into one length-prefixed frame.

    Args:
        message: An instance of one of the types in `_FRAME_MODELS`.

    Returns:
        `<4-byte big-endian length><JSON body>` ready to write to a stream.

    Raises:
        FrameTooLargeError: the serialised body exceeds MAX_FRAME_BYTES.
        ValueError: `message`'s type is not a recognised frame type.
    """
    type_tag = next((k for k, v in _FRAME_MODELS.items() if isinstance(message, v)), None)
    if type_tag is None:
        raise ValueError(f"{type(message)!r} is not a recognised frame type")
    body = json.dumps({"type": type_tag, "payload": message.model_dump(mode="json")}).encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise FrameTooLargeError(f"frame body is {len(body)} bytes, exceeds MAX_FRAME_BYTES={MAX_FRAME_BYTES}")
    return struct.pack(_LENGTH_HEADER_FORMAT, len(body)) + body


async def decode_frame(reader: asyncio.StreamReader) -> BaseModel:
    """Read and deserialise exactly one frame from `reader`.

    Args:
        reader: An open asyncio.StreamReader (worker stdout/socket).

    Returns:
        A reconstructed instance of whichever `_FRAME_MODELS` type was encoded.

    Raises:
        FrameTooLargeError: the frame's DECLARED length exceeds
            MAX_FRAME_BYTES — the body is never read in this case (fail
            before allocating).
        asyncio.IncompleteReadError: the stream closed mid-frame (caller's
            job to interpret as "worker died", not this function's).
        ValueError: the decoded `type` tag is not recognised.
    """
    header = await reader.readexactly(_LENGTH_HEADER_SIZE)
    (declared_length,) = struct.unpack(_LENGTH_HEADER_FORMAT, header)
    if declared_length > MAX_FRAME_BYTES:
        raise FrameTooLargeError(f"frame declares {declared_length} bytes, exceeds MAX_FRAME_BYTES={MAX_FRAME_BYTES}")
    body = await reader.readexactly(declared_length)
    envelope = json.loads(body)
    type_tag = envelope["type"]
    model_cls = _FRAME_MODELS.get(type_tag)
    if model_cls is None:
        raise ValueError(f"unrecognised frame type {type_tag!r}")
    return model_cls.model_validate(envelope["payload"])
