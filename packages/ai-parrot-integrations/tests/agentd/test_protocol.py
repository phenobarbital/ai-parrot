"""Unit tests for parrot.integrations.agentd.protocol (TASK-2208)."""

from __future__ import annotations

import asyncio
import json

import pytest
from parrot.integrations.agentd.protocol import (
    DEFAULT_MAX_LINE_BYTES,
    MalformedMessageError,
    OversizedLineError,
    RpcError,
    RpcNotification,
    RpcRequest,
    RpcResponse,
    read_message,
    write_message,
)


class _FakeWriter:
    """Minimal stand-in for asyncio.StreamWriter — collects written bytes."""

    def __init__(self) -> None:
        self.buffer = bytearray()

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)


class TestModels:
    def test_request_roundtrip(self):
        req = RpcRequest(id=1, method="chat.send", params={"prompt": "hi"})
        dumped = req.model_dump_json()
        restored = RpcRequest.model_validate_json(dumped)
        assert restored == req
        assert restored.jsonrpc == "2.0"
        assert restored.method == "chat.send"
        assert restored.params == {"prompt": "hi"}

    def test_response_error_shape(self):
        err = RpcError(code=-32601, message="Method not found")
        resp = RpcResponse(id=1, error=err)
        assert resp.result is None
        assert resp.error is not None
        assert resp.error.code == -32601

        dumped = resp.model_dump_json()
        restored = RpcResponse.model_validate_json(dumped)
        assert restored.error.code == -32601
        assert restored.error.message == "Method not found"

    def test_notification_has_no_id(self):
        note = RpcNotification(method="chat.delta", params={"stream_id": "s1", "text": "hi"})
        dumped = note.model_dump(mode="json")
        assert "id" not in dumped
        assert dumped["method"] == "chat.delta"


class TestFraming:
    @pytest.mark.asyncio
    async def test_split_frame(self):
        """A single message delivered across two feed_data() calls."""
        reader = asyncio.StreamReader()
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "agent.info", "params": {}})
        raw = (payload + "\n").encode("utf-8")
        mid = len(raw) // 2
        reader.feed_data(raw[:mid])
        reader.feed_data(raw[mid:])
        reader.feed_eof()

        msg = await read_message(reader)
        assert isinstance(msg, RpcRequest)
        assert msg.method == "agent.info"
        assert msg.id == 1

    @pytest.mark.asyncio
    async def test_coalesced_frames(self):
        """Two messages delivered in a single feed_data() call."""
        reader = asyncio.StreamReader()
        m1 = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "agent.info", "params": {}})
        m2 = json.dumps({"jsonrpc": "2.0", "method": "event.shutdown", "params": {}})
        reader.feed_data((m1 + "\n" + m2 + "\n").encode("utf-8"))
        reader.feed_eof()

        first = await read_message(reader)
        second = await read_message(reader)

        assert isinstance(first, RpcRequest)
        assert first.method == "agent.info"
        assert isinstance(second, RpcNotification)
        assert second.method == "event.shutdown"

    @pytest.mark.asyncio
    async def test_oversized_line_rejected(self):
        reader = asyncio.StreamReader(limit=64)
        huge_params = {"blob": "x" * 1024}
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "chat.send", "params": huge_params}
        )
        reader.feed_data((payload + "\n").encode("utf-8"))
        reader.feed_eof()

        with pytest.raises(OversizedLineError):
            await read_message(reader, max_line_bytes=32)

    @pytest.mark.asyncio
    async def test_oversized_line_default_limit_not_triggered_by_small_payload(self):
        reader = asyncio.StreamReader()
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "agent.info", "params": {}})
        reader.feed_data((payload + "\n").encode("utf-8"))
        reader.feed_eof()

        msg = await read_message(reader, max_line_bytes=DEFAULT_MAX_LINE_BYTES)
        assert isinstance(msg, RpcRequest)

    @pytest.mark.asyncio
    async def test_malformed_json(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b"{not valid json\n")
        reader.feed_eof()

        with pytest.raises(MalformedMessageError):
            await read_message(reader)

    @pytest.mark.asyncio
    async def test_malformed_shape_neither_request_nor_notification(self):
        """Valid JSON object, but not a recognizable JSON-RPC shape."""
        reader = asyncio.StreamReader()
        reader.feed_data(b'{"foo": "bar"}\n')
        reader.feed_eof()

        # No "id", no "result"/"error" -> parsed as a notification lacking
        # "method" -> pydantic validation error -> MalformedMessageError.
        with pytest.raises(MalformedMessageError):
            await read_message(reader)

    @pytest.mark.asyncio
    async def test_clean_eof_returns_none(self):
        reader = asyncio.StreamReader()
        reader.feed_eof()
        assert await read_message(reader) is None

    def test_write_message_produces_ndjson_line(self):
        writer = _FakeWriter()
        req = RpcRequest(id=1, method="agent.info", params={})
        write_message(writer, req)

        raw = bytes(writer.buffer)
        assert raw.endswith(b"\n")
        assert raw.count(b"\n") == 1
        decoded = json.loads(raw.decode("utf-8"))
        assert decoded["method"] == "agent.info"
        assert decoded["id"] == 1
