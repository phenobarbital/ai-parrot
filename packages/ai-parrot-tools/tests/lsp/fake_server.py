"""Deterministic, scripted fake LSP server for FEAT-580 M2 protocol tests.

This is a standalone test-process fixture, invoked as a subprocess
(``python fake_server.py <scenario>``) — never imported by the test suite
or by ``parrot_tools.lsp`` itself. It implements its own minimal,
synchronous ``Content-Length`` reader/writer rather than reusing
``parrot_tools.lsp.protocol``, so that ``protocol.py``'s async framing is
verified against an independent byte-level implementation instead of
being tested against its own encoder/decoder circularly.

Each scenario is a deterministic, explicit transcript selected by
``sys.argv[1]``:

- ``happy_path`` — a normal ``initialize``/``initialized`` handshake,
  followed by an interleaved ``workspace/configuration`` server-to-client
  request, a ``textDocument/publishDiagnostics`` notification, a
  ``$/progress`` notification, and then an echo response for every
  further request until ``exit``.
- ``fragmented_writes`` — the same transcript as ``happy_path``, but every
  outgoing frame is written a few bytes at a time with short sleeps, to
  exercise a client reading fragmented headers/bodies over a real pipe.
- ``flood_stderr`` — the same transcript as ``happy_path``, plus a
  background thread that continuously floods stderr, to prove stdout
  framing is unaffected by unrelated stderr traffic.
- ``delay_response`` — accepts ``initialize`` but never answers it within
  any reasonable test timeout, to exercise caller-side timeout/cancellation.
- ``omit_response`` — answers ``initialize`` once, then silently drops
  every subsequent request without ever answering it.
- ``refuse_shutdown`` — answers ``initialize``, then ignores every further
  message (including ``shutdown``/``exit``) and keeps running until killed.
- ``early_eof`` — exits immediately without reading or answering anything,
  simulating a child that crashed before startup completed.
- ``malformed_header`` — answers ``initialize``, then writes one frame
  whose ``Content-Length`` value is not an integer.
- ``oversized_header`` — answers ``initialize``, then writes one frame
  header declaring a body far larger than any client-side cap, without
  ever writing that much body data.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from typing import Any, BinaryIO

#: Chunk size used by the fragmented-write scenarios; deliberately small
#: (and deliberately not aligned to header/body boundaries) so a client
#: reading this stream must genuinely handle fragmentation.
_FRAGMENT_CHUNK_BYTES = 3
_FRAGMENT_DELAY_S = 0.001

#: Total stderr bytes written by the stderr-flood scenario.
_STDERR_FLOOD_BYTES = 128 * 1024


def _read_frame(stream: BinaryIO) -> dict[str, Any] | None:
    """Read one ``Content-Length``-framed JSON object, or ``None`` at EOF."""
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        decoded = line.decode("ascii").rstrip("\r\n")
        name, _sep, value = decoded.partition(":")
        headers[name.strip().lower()] = value.strip()
    length = int(headers["content-length"])
    body = stream.read(length)
    if body is None or len(body) < length:
        return None
    return json.loads(body.decode("utf-8"))


def _write_frame(stream: BinaryIO, message: dict[str, Any], *, fragment: bool = False) -> None:
    """Write one ``Content-Length``-framed JSON object, whole or fragmented."""
    body = json.dumps(message).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    payload = header + body
    if not fragment:
        stream.write(payload)
        stream.flush()
        return
    for offset in range(0, len(payload), _FRAGMENT_CHUNK_BYTES):
        stream.write(payload[offset : offset + _FRAGMENT_CHUNK_BYTES])
        stream.flush()
        time.sleep(_FRAGMENT_DELAY_S)


def _respond(stream: BinaryIO, request: dict[str, Any], result: Any, *, fragment: bool = False) -> None:
    _write_frame(stream, {"jsonrpc": "2.0", "id": request["id"], "result": result}, fragment=fragment)


def _server_request(stream: BinaryIO, request_id: int, method: str, params: Any, *, fragment: bool = False) -> None:
    _write_frame(
        stream,
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        fragment=fragment,
    )


def _notify(stream: BinaryIO, method: str, params: Any, *, fragment: bool = False) -> None:
    _write_frame(stream, {"jsonrpc": "2.0", "method": method, "params": params}, fragment=fragment)


def _flood_stderr() -> None:
    chunk = ("x" * 1024 + "\n").encode("utf-8")
    written = 0
    while written < _STDERR_FLOOD_BYTES:
        sys.stderr.buffer.write(chunk)
        sys.stderr.buffer.flush()
        written += len(chunk)


def _run_handshake_and_echo_loop(*, fragment: bool = False) -> None:
    """``initialize`` -> interleaved config/diagnostics/progress -> echo loop."""
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    request = _read_frame(stdin)
    if request is None or request.get("method") != "initialize":
        return
    _respond(stdout, request, {"capabilities": {}}, fragment=fragment)

    if _read_frame(stdin) is None:  # "initialized" notification
        return

    _server_request(stdout, 9001, "workspace/configuration", {"items": [{"section": "python"}]}, fragment=fragment)
    if _read_frame(stdin) is None:  # the client's configuration response
        return

    _notify(
        stdout,
        "textDocument/publishDiagnostics",
        {"uri": "file:///scenario.py", "version": 1, "diagnostics": []},
        fragment=fragment,
    )
    _notify(stdout, "$/progress", {"token": "scenario", "value": {"kind": "report"}}, fragment=fragment)

    while True:
        message = _read_frame(stdin)
        if message is None:
            return
        method = message.get("method")
        if method == "exit":
            return
        if "id" in message and method is not None:
            _respond(stdout, message, {"echo": method}, fragment=fragment)


def run_happy_path() -> None:
    _run_handshake_and_echo_loop(fragment=False)


def run_fragmented_writes() -> None:
    _run_handshake_and_echo_loop(fragment=True)


def run_flood_stderr() -> None:
    threading.Thread(target=_flood_stderr, daemon=True).start()
    _run_handshake_and_echo_loop(fragment=False)


def run_delay_response() -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    request = _read_frame(stdin)
    if request is None:
        return
    time.sleep(60.0)
    _respond(stdout, request, {"capabilities": {}})


def run_omit_response() -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    request = _read_frame(stdin)
    if request is None or request.get("method") != "initialize":
        return
    _respond(stdout, request, {"capabilities": {}})
    while True:
        if _read_frame(stdin) is None:
            return
        # Every further request is read (drained) but never answered.


def run_refuse_shutdown() -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    request = _read_frame(stdin)
    if request is None or request.get("method") != "initialize":
        return
    _respond(stdout, request, {"capabilities": {}})
    while True:
        if _read_frame(stdin) is None:
            return
        # shutdown/exit and everything else is drained and ignored; the
        # process only ever stops when the caller kills it.


def run_early_eof() -> None:
    sys.stdout.buffer.close()


def run_malformed_header() -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    request = _read_frame(stdin)
    if request is None:
        return
    _respond(stdout, request, {"capabilities": {}})
    stdout.write(b"Content-Length: not-a-number\r\n\r\n")
    stdout.flush()


def run_oversized_header() -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    request = _read_frame(stdin)
    if request is None:
        return
    _respond(stdout, request, {"capabilities": {}})
    stdout.write(b"Content-Length: 67108864\r\n\r\n")  # 64 MiB, never actually sent
    stdout.flush()


_SCENARIOS = {
    "happy_path": run_happy_path,
    "fragmented_writes": run_fragmented_writes,
    "flood_stderr": run_flood_stderr,
    "delay_response": run_delay_response,
    "omit_response": run_omit_response,
    "refuse_shutdown": run_refuse_shutdown,
    "early_eof": run_early_eof,
    "malformed_header": run_malformed_header,
    "oversized_header": run_oversized_header,
}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in _SCENARIOS:
        sys.stderr.write(f"usage: fake_server.py {{{'|'.join(sorted(_SCENARIOS))}}}\n")
        return 2
    _SCENARIOS[argv[1]]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
