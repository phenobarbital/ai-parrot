"""Unit tests for services/sandbox/protocol.py — FEAT-459 / TASK-3168."""

from __future__ import annotations

import asyncio
import struct

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
    # BrokerRequest with a payload large enough to push the serialised
    # body past MAX_FRAME_BYTES — simplest oversized fixture available.
    huge_request = BrokerRequest(
        kind="http_hosts",
        target="api.example.com",
        args={"blob": "x" * (MAX_FRAME_BYTES + 1024)},
    )
    with pytest.raises(FrameTooLargeError):
        encode_frame(huge_request)


async def test_decode_rejects_oversized_declared_length() -> None:
    """A declared length > MAX_FRAME_BYTES is rejected WITHOUT reading the body."""
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


async def test_encode_decode_round_trip_sandbox_outcome() -> None:
    original = SandboxOutcome(duration_ms=12.5, broker_calls=2)
    frame = encode_frame(original)
    decoded = await decode_frame(_reader_from_bytes(frame))
    assert decoded == original
