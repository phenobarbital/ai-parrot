# TASK-3168: Worker wire protocol — `services/sandbox/protocol.py`

**Feature**: FEAT-459 — Form Builder: Sandboxed Custom Code on Lifecycle Events
**Spec**: `sdd/specs/formbuilder-custom-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3161
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8. Both worker pools (TASK-3169 subprocess, TASK-3170
gVisor) talk to their child processes over stdio using the SAME framing —
this module is that shared wire format: length-prefixed JSON with a strict
size cap. `SandboxContext` goes in; `SandboxOutcome`, `AbortSignal`, or a
`BrokerRequest` come out. This is pure serialization/framing code — no
process management (that is TASK-3169/3170) and no broker logic (that is
TASK-3171).

---

## Scope

- Define `BrokerRequest`/`BrokerResponse` in this module (they are named
  in spec §2's `HostBroker.handle()` signature but not defined in §2 Data
  Models — this task defines their shape, since M8 owns the wire protocol
  and both are wire messages).
- Implement `encode_frame(message) -> bytes` and `decode_frame(reader) ->
  Message` — length-prefixed (4-byte big-endian length header + JSON
  body), with a hard `MAX_FRAME_BYTES` cap that **rejects** an oversized
  frame rather than truncating it.
- Write `packages/parrot-formdesigner/tests/unit/test_sandbox_protocol.py`.

**NOT in scope**: `asyncio.subprocess` process spawning (TASK-3169);
gVisor/`SandboxConfig` (TASK-3170); actual broker request handling
(TASK-3171) — this task only defines and (de)serializes the message
shapes those tasks pass over the wire.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/protocol.py` | CREATE | Frame encode/decode + `BrokerRequest`/`BrokerResponse` |
| `packages/parrot-formdesigner/tests/unit/test_sandbox_protocol.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.snippets import SandboxContext, SandboxOutcome  # TASK-3161
```

### Existing Signatures to Use
```python
# spec §2 New Public Interfaces — the broker method THIS module's
# BrokerRequest/BrokerResponse types must satisfy:
class HostBroker:
    async def handle(
        self, request: BrokerRequest, manifest: CapabilityManifest,
    ) -> BrokerResponse:
        """Raises CapabilityDenied when the request is outside the allowlist."""
```

### Does NOT Exist
- ~~`BrokerRequest` / `BrokerResponse`~~ — named in spec §2's interface
  skeleton but never defined as a concrete model anywhere in the spec
  body or the current codebase. **This task defines them for the first
  time** — see blueprint. Do not assume a shape beyond what this task's
  blueprint specifies; if TASK-3171 (Host Broker) needs additional
  fields, it should extend this module, not redefine the type elsewhere.
- ~~`services/sandbox/protocol.py`~~ — created by this task.
- ~~Any existing length-prefixed framing utility in this repo~~ — searched,
  none found under `packages/parrot-formdesigner/` or `packages/ai-parrot/`;
  this is new code, not a wrapper around an existing helper.

---

## Implementation Notes

### Key Constraints
- **Reject, never truncate**, an oversized frame — a silently truncated
  JSON body is a worse failure mode than a loud `FrameTooLargeError`
  (spec `test_protocol_enforces_size_cap`: "Oversized frame rejected, not
  truncated").
- Length prefix is a fixed-width 4-byte big-endian unsigned integer
  (`struct.pack(">I", len(body))`) — this bounds a single frame to 4 GiB
  before even reaching `MAX_FRAME_BYTES`, but the actual enforced cap
  should be far smaller (a snippet payload is form-sized data, not a file
  upload) — default `MAX_FRAME_BYTES = 1_048_576` (1 MiB) as a starting
  point, configurable.
- `asyncio.StreamReader.readexactly()` is the correct primitive for
  reading a fixed-length header, then the body — it raises
  `asyncio.IncompleteReadError` on a closed/short stream, which callers
  (TASK-3169/3170) should treat as "worker died", not swallow here.
- No blocking I/O — this module's decode side takes an
  `asyncio.StreamReader`, never a raw socket or file object requiring
  synchronous reads.

### References in Codebase
- None — this is genuinely new protocol code with no existing precedent
  in this repo to follow beyond the general async-first convention.

---

## Implementation Blueprint

### Steps (in order)
1. Define `BrokerRequest`/`BrokerResponse` — *why*: needed before the
   frame `Message` union type can be written.
2. Define `MAX_FRAME_BYTES` and `FrameTooLargeError`.
3. Implement `encode_frame()`.
4. Implement `decode_frame()`.
5. Write and run tests, prioritizing the size-cap test.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/protocol.py` (CREATE)
```python
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
        raise FrameTooLargeError(
            f"frame body is {len(body)} bytes, exceeds MAX_FRAME_BYTES={MAX_FRAME_BYTES}"
        )
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
        raise FrameTooLargeError(
            f"frame declares {declared_length} bytes, exceeds MAX_FRAME_BYTES={MAX_FRAME_BYTES}"
        )
    body = await reader.readexactly(declared_length)
    envelope = json.loads(body)
    type_tag = envelope["type"]
    model_cls = _FRAME_MODELS.get(type_tag)
    if model_cls is None:
        raise ValueError(f"unrecognised frame type {type_tag!r}")
    return model_cls.model_validate(envelope["payload"])
```
**Why this shape**: the `type` tag inside the JSON body (rather than a
separate byte in the header) keeps the header format trivial (just a
length) while still letting `decode_frame()` reconstruct the correct
Pydantic model — a worker process only ever sends `sandbox_outcome`,
`abort_signal`, or `broker_request` frames, and only ever receives
`sandbox_context` or `broker_response` frames, but this module does not
enforce that direction-specific subset — that is a TASK-3169/3170/3171
protocol-usage concern, not a framing concern.

### `packages/parrot-formdesigner/tests/unit/test_sandbox_protocol.py` (CREATE)
```python
"""Unit tests for services/sandbox/protocol.py — FEAT-459 / TASK-3168."""

from __future__ import annotations

import asyncio

import pytest

from parrot_formdesigner.core.snippets import AbortSignal, SandboxOutcome
from parrot_formdesigner.services.sandbox.protocol import (
    MAX_FRAME_BYTES,
    BrokerRequest,
    FrameTooLargeError,
    decode_frame,
    encode_frame,
)


def _reader_from_bytes(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


async def test_encode_decode_round_trip_abort_signal() -> None:
    original = AbortSignal(reason="policy", user_message="Not allowed", status_code=403)
    frame = encode_frame(original)
    decoded = await decode_frame(_reader_from_bytes(frame))
    assert decoded == original


async def test_encode_decode_round_trip_broker_request() -> None:
    original = BrokerRequest(kind="http_hosts", target="api.example.com", args={"method": "GET"})
    frame = encode_frame(original)
    decoded = await decode_frame(_reader_from_bytes(frame))
    assert decoded == original


def test_encode_rejects_oversized_body() -> None:
    huge_outcome = SandboxOutcome(duration_ms=1.0, broker_calls=0)
    # FILL IN: monkeypatch or construct a message whose model_dump()
    #   serialises to > MAX_FRAME_BYTES (e.g. a SandboxOutcome with an
    #   oversized `resolution.metadata` blob) and assert
    #   pytest.raises(FrameTooLargeError) from encode_frame().
    pass


async def test_decode_rejects_oversized_declared_length() -> None:
    """A declared length > MAX_FRAME_BYTES is rejected WITHOUT reading the body."""
    import struct
    header = struct.pack(">I", MAX_FRAME_BYTES + 1)
    reader = _reader_from_bytes(header)  # no body follows — must fail on the header alone
    with pytest.raises(FrameTooLargeError):
        await decode_frame(reader)


async def test_decode_raises_on_truncated_stream() -> None:
    frame = encode_frame(AbortSignal(reason="x", user_message="y"))
    truncated = frame[:-2]  # cut off part of the body
    with pytest.raises(asyncio.IncompleteReadError):
        await decode_frame(_reader_from_bytes(truncated))


def test_encode_unrecognised_type_raises() -> None:
    class _NotAFrameType:
        pass

    with pytest.raises(ValueError):
        encode_frame(_NotAFrameType())  # type: ignore[arg-type]
```
**Why**: the size-cap test on the decode side (checking the DECLARED
length before reading the body) is the one that most directly proves "not
truncated, rejected" and is written in full; the encode-side size-cap test
is stubbed since constructing an over-1MiB Pydantic model inline is
verbose — the implementer should pick the simplest oversized fixture.

### FILL IN checklist
- [ ] `test_encode_rejects_oversized_body` — construct an oversized message and assert `FrameTooLargeError`

---

## Acceptance Criteria

- [ ] `encode_frame()`/`decode_frame()` round-trip every type in `_FRAME_MODELS` without loss
- [ ] `encode_frame()` raises `FrameTooLargeError` for a body exceeding `MAX_FRAME_BYTES`, without ever writing a truncated frame
- [ ] `decode_frame()` raises `FrameTooLargeError` from the DECLARED length alone, before reading the body (verified: the test constructs a header with no following bytes and still gets the size error, not a stream error)
- [ ] `decode_frame()` propagates `asyncio.IncompleteReadError` on a truncated stream rather than returning a partial/corrupt object
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_sandbox_protocol.py -v`
- [ ] `ruff check` and `mypy` clean on `services/sandbox/protocol.py`

---

## Test Specification

See the blueprint's test file above — 5 test functions, 1 stubbed.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 New Public Interfaces `HostBroker.handle()`, §3 Module 8)
2. **Check dependencies** — TASK-3161 must be `done`
3. **Verify the Codebase Contract** — confirm no `BrokerRequest`/`BrokerResponse` definition has been added elsewhere in the meantime (would indicate a conflicting parallel task)
4. **Update status** in `sdd/tasks/index/formbuilder-custom-code.json` → `"in-progress"`
5. **Implement** from the blueprint; complete the one `# FILL IN:`
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3168-worker-protocol.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (direct implementation — parrot-sdd-coder's
two dispatch attempts both failed before producing any code)
**Date**: 2026-09-11
**Notes**: Implemented `encode_frame()`/`decode_frame()` length-prefixed
JSON framing exactly per the blueprint, plus `BrokerRequest`,
`BrokerResponse`, `FrameTooLargeError`, and `MAX_FRAME_BYTES` (1 MiB).
Completed the one FILL IN (`test_encode_rejects_oversized_body`) using a
`BrokerRequest` with an oversized `args` blob as the simplest fixture.
Added one extra round-trip test for `SandboxOutcome` beyond the
blueprint's 5. 7/7 tests pass, `ruff check` and `mypy` clean on
`services/sandbox/protocol.py`.

**Deviations from spec**: none — added 1 test beyond the blueprint
(`SandboxOutcome` round-trip), exercising the "round-trips every type in
`_FRAME_MODELS`" acceptance criterion more completely.

**Seat: sonnet (orchestrator, direct attempt 3 after 2 dispatch failures) · Backend: n/a · Model: claude-sonnet-5 · Attempts: 1 · Duration: n/a (interactive) · Tokens: n/a**

**Prior failed dispatch attempts** (for the record):
1. `codex-spark` (codex backend, `gpt-5.3-codex-spark`) — failed
   immediately: `codex exec` CLI rejected `--ask-for-approval` as an
   unexpected argument (dispatcher/CLI version mismatch, not a task
   issue).
2. `qwen` (nova backend, `qwen.qwen3-coder-480b-a35b-instruct`) — request
   timed out after 551s with no code produced.
