"""Unit/integration tests for FEAT-580 M2 bounded LSP framing.

Framing/discrimination/bounds are exercised purely in-memory against a
manually fed :class:`asyncio.StreamReader` (no process, no Pyright, no
network). Fault handling against a real, independently-implemented child
process is exercised through the scripted ``fake_server.py`` fixture over
genuine subprocess pipes.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from parrot_tools.lsp.models import LSPFailure
from parrot_tools.lsp.protocol import (
    build_notification,
    build_request,
    build_response,
    read_message,
    write_message,
)

FAKE_SERVER = Path(__file__).parent / "fake_server.py"

#: Generous per-read timeout for a well-behaved scenario; failures in a
#: healthy exchange should never legitimately take this long.
_READ_TIMEOUT_S = 5.0
#: Short timeout used to prove a call is genuinely hanging/dropped.
_HANG_TIMEOUT_S = 0.2


def _encode_frame(message: dict) -> bytes:
    """Encode ``message`` exactly like :func:`write_message` would."""
    body = json.dumps(message).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def _fed_reader(*chunks: bytes, eof: bool = True) -> asyncio.StreamReader:
    """An :class:`asyncio.StreamReader` pre-loaded with ``chunks``."""
    reader = asyncio.StreamReader()
    for chunk in chunks:
        reader.feed_data(chunk)
    if eof:
        reader.feed_eof()
    return reader


class _MemoryWriter:
    """A minimal ``write()``/``drain()`` sink with no real transport."""

    def __init__(self) -> None:
        self.buffer = bytearray()

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        return None


async def _spawn_scenario(scenario: str) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        str(FAKE_SERVER),
        scenario,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    if proc.stdin is not None and not proc.stdin.is_closing():
        proc.stdin.close()
    if proc.returncode is None:
        proc.kill()
    await proc.wait()


# ---------------------------------------------------------------------------
# test_framing_and_interleaving
# ---------------------------------------------------------------------------


class TestFramingAndInterleaving:
    @pytest.mark.asyncio
    async def test_framing_and_interleaving(self) -> None:
        """Multiple frames buffered from one read discriminate correctly."""
        request = build_request(1, "textDocument/definition", {"line": 0})
        notification = build_notification("textDocument/publishDiagnostics", {"diagnostics": []})
        response = build_response(1, result={"ok": True})

        combined = _encode_frame(request) + _encode_frame(notification) + _encode_frame(response)
        reader = _fed_reader(combined)

        first = await read_message(reader)
        second = await read_message(reader)
        third = await read_message(reader)

        assert first.kind == "request"
        assert first.id == 1
        assert first.method == "textDocument/definition"
        assert first.params == {"line": 0}

        assert second.kind == "notification"
        assert second.id is None
        assert second.method == "textDocument/publishDiagnostics"

        assert third.kind == "response"
        assert third.id == 1
        assert third.result == {"ok": True}
        assert third.error is None

    @pytest.mark.asyncio
    async def test_framing_handles_fragmented_header_and_body(self) -> None:
        """A header/body trickling in byte-by-byte still parses correctly."""
        message = build_request(2, "initialize", {"processId": None})
        frame = _encode_frame(message)

        reader = asyncio.StreamReader()
        task = asyncio.ensure_future(read_message(reader))
        for offset in range(0, len(frame), 5):
            reader.feed_data(frame[offset : offset + 5])
            await asyncio.sleep(0)
        parsed = await asyncio.wait_for(task, timeout=_READ_TIMEOUT_S)

        assert parsed.kind == "request"
        assert parsed.method == "initialize"
        assert parsed.id == 2
        assert parsed.params == {"processId": None}

    @pytest.mark.asyncio
    async def test_error_response_discriminates_correctly(self) -> None:
        error_response = build_response(7, error={"code": -32601, "message": "method not found"})
        reader = _fed_reader(_encode_frame(error_response))

        parsed = await read_message(reader)

        assert parsed.kind == "response"
        assert parsed.id == 7
        assert parsed.result is None
        assert parsed.error == {"code": -32601, "message": "method not found"}

    @pytest.mark.asyncio
    async def test_string_and_int_request_ids_are_preserved(self) -> None:
        int_request = build_request(42, "workspace/configuration", None)
        string_request = build_request("req-abc", "workspace/configuration", None)
        reader = _fed_reader(_encode_frame(int_request) + _encode_frame(string_request))

        first = await read_message(reader)
        second = await read_message(reader)

        assert first.id == 42 and isinstance(first.id, int)
        assert second.id == "req-abc" and isinstance(second.id, str)


# ---------------------------------------------------------------------------
# test_unicode_content_length_counts_bytes
# ---------------------------------------------------------------------------


class TestUnicodeContentLength:
    @pytest.mark.asyncio
    async def test_unicode_content_length_counts_bytes(self) -> None:
        """Content-Length is the UTF-8 byte count, never the char count."""
        text = "café \U0001f600 你好"  # accents + emoji + CJK
        message = build_notification("window/logMessage", {"type": 3, "message": text})

        # ``write_message`` encodes with ``ensure_ascii=False`` and compact
        # separators (see below), so the sanity check must match that
        # exact encoding to be meaningful — the default ``ensure_ascii=True``
        # escapes every non-ASCII character into a pure-ASCII ``\uXXXX``
        # sequence, which would make byte length and char length trivially
        # equal.
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        char_length = len(encoded)
        byte_length = len(encoded.encode("utf-8"))
        assert byte_length != char_length  # sanity: multi-byte chars really differ

        writer = _MemoryWriter()
        await write_message(writer, message)

        raw = bytes(writer.buffer)
        header_block, _, remainder = raw.partition(b"\r\n\r\n")
        declared_length = int(header_block.split(b":", 1)[1].strip())
        assert declared_length == byte_length
        assert len(remainder) == byte_length

        reader = _fed_reader(raw)
        parsed = await read_message(reader)
        assert parsed.params["message"] == text

    @pytest.mark.asyncio
    async def test_hand_built_unicode_frame_round_trips(self) -> None:
        """A frame built by hand, with a byte length, parses correctly."""
        payload = {"jsonrpc": "2.0", "method": "window/logMessage", "params": {"message": "ééé"}}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        assert len(body) != len(json.dumps(payload, ensure_ascii=False))  # 3 accented chars, 6 bytes

        frame = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        reader = _fed_reader(frame)

        parsed = await read_message(reader)
        assert parsed.kind == "notification"
        assert parsed.params["message"] == "ééé"

    @pytest.mark.asyncio
    async def test_write_message_rejects_oversized_payload(self) -> None:
        writer = _MemoryWriter()
        with pytest.raises(LSPFailure) as excinfo:
            await write_message(writer, build_notification("x", {"data": "y" * 100}), max_frame_bytes=10)
        assert excinfo.value.code == "protocol_error"


# ---------------------------------------------------------------------------
# test_oversized_and_malformed_frames
# ---------------------------------------------------------------------------


class TestOversizedAndMalformedFrames:
    @pytest.mark.asyncio
    async def test_oversized_declared_length_rejected_before_reading_body(self) -> None:
        oversized_header = b"Content-Length: 999999999\r\n\r\n"
        reader = _fed_reader(oversized_header)
        with pytest.raises(LSPFailure) as excinfo:
            await read_message(reader, max_frame_bytes=1024)
        assert excinfo.value.code == "protocol_error"

    @pytest.mark.asyncio
    async def test_non_integer_content_length_rejected(self) -> None:
        reader = _fed_reader(b"Content-Length: not-a-number\r\n\r\n")
        with pytest.raises(LSPFailure) as excinfo:
            await read_message(reader)
        assert excinfo.value.code == "protocol_error"

    @pytest.mark.asyncio
    async def test_negative_content_length_rejected(self) -> None:
        reader = _fed_reader(b"Content-Length: -1\r\n\r\n")
        with pytest.raises(LSPFailure) as excinfo:
            await read_message(reader)
        assert excinfo.value.code == "protocol_error"

    @pytest.mark.asyncio
    async def test_missing_content_length_header_rejected(self) -> None:
        reader = _fed_reader(b"X-Other: 1\r\n\r\n")
        with pytest.raises(LSPFailure) as excinfo:
            await read_message(reader)
        assert excinfo.value.code == "protocol_error"

    @pytest.mark.asyncio
    async def test_non_json_body_rejected(self) -> None:
        body = b"not json"
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        reader = _fed_reader(header + body)
        with pytest.raises(LSPFailure) as excinfo:
            await read_message(reader)
        assert excinfo.value.code == "protocol_error"

    @pytest.mark.asyncio
    async def test_non_object_json_body_rejected(self) -> None:
        body = b"[1, 2, 3]"
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        reader = _fed_reader(header + body)
        with pytest.raises(LSPFailure) as excinfo:
            await read_message(reader)
        assert excinfo.value.code == "protocol_error"

    @pytest.mark.asyncio
    async def test_wrong_jsonrpc_version_rejected(self) -> None:
        body = json.dumps({"jsonrpc": "1.0", "method": "x"}).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        reader = _fed_reader(header + body)
        with pytest.raises(LSPFailure) as excinfo:
            await read_message(reader)
        assert excinfo.value.code == "protocol_error"

    @pytest.mark.asyncio
    async def test_response_with_neither_result_nor_error_rejected(self) -> None:
        body = json.dumps({"jsonrpc": "2.0", "id": 1}).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        reader = _fed_reader(header + body)
        with pytest.raises(LSPFailure) as excinfo:
            await read_message(reader)
        assert excinfo.value.code == "protocol_error"

    @pytest.mark.asyncio
    async def test_response_with_both_result_and_error_rejected(self) -> None:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}, "error": {"code": -1, "message": "x"}}).encode(
            "utf-8"
        )
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        reader = _fed_reader(header + body)
        with pytest.raises(LSPFailure) as excinfo:
            await read_message(reader)
        assert excinfo.value.code == "protocol_error"

    @pytest.mark.asyncio
    async def test_boolean_id_rejected(self) -> None:
        body = json.dumps({"jsonrpc": "2.0", "id": True, "method": "x"}).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        reader = _fed_reader(header + body)
        with pytest.raises(LSPFailure) as excinfo:
            await read_message(reader)
        assert excinfo.value.code == "protocol_error"

    @pytest.mark.asyncio
    async def test_oversized_header_block_rejected(self) -> None:
        huge_header = b"X-Filler: " + b"a" * 9000 + b"\r\n\r\n"
        reader = _fed_reader(huge_header)
        with pytest.raises(LSPFailure) as excinfo:
            await read_message(reader, max_header_bytes=8192)
        assert excinfo.value.code == "protocol_error"

    @pytest.mark.asyncio
    async def test_premature_eof_before_headers_is_server_crashed(self) -> None:
        reader = _fed_reader(b"", eof=True)
        with pytest.raises(LSPFailure) as excinfo:
            await read_message(reader)
        assert excinfo.value.code == "server_crashed"

    @pytest.mark.asyncio
    async def test_premature_eof_mid_body_is_server_crashed(self) -> None:
        partial_header = b"Content-Length: 5\r\n\r\n"
        reader = _fed_reader(partial_header + b"ab", eof=True)
        with pytest.raises(LSPFailure) as excinfo:
            await read_message(reader)
        assert excinfo.value.code == "server_crashed"

    @pytest.mark.asyncio
    async def test_premature_eof_mid_header_is_server_crashed(self) -> None:
        reader = _fed_reader(b"Content-Length: 5", eof=True)
        with pytest.raises(LSPFailure) as excinfo:
            await read_message(reader)
        assert excinfo.value.code == "server_crashed"


# ---------------------------------------------------------------------------
# test_fake_child_fault_scenarios
# ---------------------------------------------------------------------------


class TestFakeChildFaultScenarios:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", ["happy_path", "fragmented_writes"])
    async def test_handshake_with_interleaved_notifications(self, scenario: str) -> None:
        proc = await _spawn_scenario(scenario)
        try:
            await write_message(proc.stdin, build_request(1, "initialize", {"processId": None}))
            init_response = await asyncio.wait_for(read_message(proc.stdout), timeout=_READ_TIMEOUT_S)
            assert init_response.kind == "response" and init_response.id == 1

            await write_message(proc.stdin, build_notification("initialized", {}))

            config_request = await asyncio.wait_for(read_message(proc.stdout), timeout=_READ_TIMEOUT_S)
            assert config_request.kind == "request"
            assert config_request.method == "workspace/configuration"
            await write_message(proc.stdin, build_response(config_request.id, result=[{}]))

            diagnostics = await asyncio.wait_for(read_message(proc.stdout), timeout=_READ_TIMEOUT_S)
            assert diagnostics.kind == "notification"
            assert diagnostics.method == "textDocument/publishDiagnostics"

            progress = await asyncio.wait_for(read_message(proc.stdout), timeout=_READ_TIMEOUT_S)
            assert progress.kind == "notification"
            assert progress.method == "$/progress"

            await write_message(proc.stdin, build_request(2, "textDocument/definition", {}))
            echoed = await asyncio.wait_for(read_message(proc.stdout), timeout=_READ_TIMEOUT_S)
            assert echoed.kind == "response" and echoed.id == 2
            assert echoed.result == {"echo": "textDocument/definition"}

            await write_message(proc.stdin, build_notification("exit", None))
        finally:
            await _terminate(proc)

    @pytest.mark.asyncio
    async def test_stderr_flood_does_not_corrupt_stdout_framing(self) -> None:
        proc = await _spawn_scenario("flood_stderr")
        try:
            await write_message(proc.stdin, build_request(1, "initialize", {}))
            init_response = await asyncio.wait_for(read_message(proc.stdout), timeout=_READ_TIMEOUT_S)
            assert init_response.kind == "response" and init_response.id == 1

            stderr_chunk = await asyncio.wait_for(proc.stderr.read(1024), timeout=_READ_TIMEOUT_S)
            assert stderr_chunk  # the flood is really happening on stderr

            await write_message(proc.stdin, build_notification("initialized", {}))
            config_request = await asyncio.wait_for(read_message(proc.stdout), timeout=_READ_TIMEOUT_S)
            assert config_request.method == "workspace/configuration"
        finally:
            await _terminate(proc)

    @pytest.mark.asyncio
    async def test_delayed_response_can_be_timed_out_and_cancelled(self) -> None:
        proc = await _spawn_scenario("delay_response")
        try:
            await write_message(proc.stdin, build_request(1, "initialize", {}))
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(read_message(proc.stdout), timeout=_HANG_TIMEOUT_S)
        finally:
            await _terminate(proc)

    @pytest.mark.asyncio
    async def test_omitted_response_can_be_timed_out(self) -> None:
        proc = await _spawn_scenario("omit_response")
        try:
            await write_message(proc.stdin, build_request(1, "initialize", {}))
            init_response = await asyncio.wait_for(read_message(proc.stdout), timeout=_READ_TIMEOUT_S)
            assert init_response.kind == "response"

            await write_message(proc.stdin, build_request(2, "textDocument/definition", {}))
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(read_message(proc.stdout), timeout=_HANG_TIMEOUT_S)
        finally:
            await _terminate(proc)

    @pytest.mark.asyncio
    async def test_refused_shutdown_forces_a_kill_that_surfaces_as_server_crashed(self) -> None:
        proc = await _spawn_scenario("refuse_shutdown")
        try:
            await write_message(proc.stdin, build_request(1, "initialize", {}))
            init_response = await asyncio.wait_for(read_message(proc.stdout), timeout=_READ_TIMEOUT_S)
            assert init_response.kind == "response"

            await write_message(proc.stdin, build_request(2, "shutdown", None))
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(read_message(proc.stdout), timeout=_HANG_TIMEOUT_S)

            proc.kill()
            await proc.wait()

            with pytest.raises(LSPFailure) as excinfo:
                await read_message(proc.stdout)
            assert excinfo.value.code == "server_crashed"
        finally:
            await _terminate(proc)

    @pytest.mark.asyncio
    async def test_early_eof_is_a_clean_server_crashed_failure(self) -> None:
        proc = await _spawn_scenario("early_eof")
        try:
            with pytest.raises(LSPFailure) as excinfo:
                await asyncio.wait_for(read_message(proc.stdout), timeout=_READ_TIMEOUT_S)
            assert excinfo.value.code == "server_crashed"
        finally:
            await _terminate(proc)

    @pytest.mark.asyncio
    async def test_malformed_header_from_a_real_child_is_protocol_error(self) -> None:
        proc = await _spawn_scenario("malformed_header")
        try:
            await write_message(proc.stdin, build_request(1, "initialize", {}))
            init_response = await asyncio.wait_for(read_message(proc.stdout), timeout=_READ_TIMEOUT_S)
            assert init_response.kind == "response"

            with pytest.raises(LSPFailure) as excinfo:
                await asyncio.wait_for(read_message(proc.stdout), timeout=_READ_TIMEOUT_S)
            assert excinfo.value.code == "protocol_error"
        finally:
            await _terminate(proc)

    @pytest.mark.asyncio
    async def test_oversized_header_from_a_real_child_is_protocol_error(self) -> None:
        proc = await _spawn_scenario("oversized_header")
        try:
            await write_message(proc.stdin, build_request(1, "initialize", {}))
            init_response = await asyncio.wait_for(read_message(proc.stdout), timeout=_READ_TIMEOUT_S)
            assert init_response.kind == "response"

            with pytest.raises(LSPFailure) as excinfo:
                await asyncio.wait_for(read_message(proc.stdout, max_frame_bytes=1024), timeout=_READ_TIMEOUT_S)
            assert excinfo.value.code == "protocol_error"
        finally:
            await _terminate(proc)
