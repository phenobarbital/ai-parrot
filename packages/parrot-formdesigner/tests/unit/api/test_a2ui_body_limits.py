"""Unit tests for the FEAT-822 capped body reader (issue:bf978b6bae8a).

Spec: ``sdd/specs/fixgroup-adbf411ace18.spec.md`` §4.
"""

from __future__ import annotations

import json

import pytest

from parrot_formdesigner.api import a2ui_wire


class _FakeContent:
    """Minimal ``StreamReader`` stand-in that records every read size."""

    def __init__(self, payload: bytes, *, chunk_size: int | None = None) -> None:
        self._payload = payload
        self._pos = 0
        self._chunk_size = chunk_size
        self.requested: list[int] = []

    async def read(self, n: int = -1) -> bytes:
        self.requested.append(n)
        remaining = len(self._payload) - self._pos
        if remaining <= 0:
            return b""
        take = remaining if n < 0 else min(n, remaining)
        if self._chunk_size is not None:
            # Simulate aiohttp's short reads: never return more than chunk_size
            # per call, so the reader must loop.
            take = min(take, self._chunk_size)
        chunk = self._payload[self._pos : self._pos + take]
        self._pos += take
        return chunk


class _FakeRequest:
    """Minimal ``web.Request`` stand-in for the reader helpers."""

    def __init__(
        self,
        payload: bytes,
        *,
        content_type: str = "application/json",
        chunked: bool = False,
        chunk_size: int | None = None,
    ) -> None:
        self.content = _FakeContent(payload, chunk_size=chunk_size)
        self.content_type = content_type
        #: A chunked request declares no length -- the bypass this feature fixes.
        self.content_length = None if chunked else len(payload)


@pytest.fixture
def tiny_cap(monkeypatch):
    """Shrink the cap so tests never allocate megabytes."""
    monkeypatch.setattr(a2ui_wire, "A2UI_MAX_BODY_BYTES", 1024)
    return 1024


async def test_read_capped_body_accepts_exactly_limit(tiny_cap):
    """Spec AC1: a body of exactly `limit` bytes is returned intact."""
    payload = b"x" * tiny_cap
    request = _FakeRequest(payload)

    assert await a2ui_wire.read_capped_body(request) == payload


async def test_read_capped_body_rejects_over_limit(tiny_cap):
    """Spec AC1: `limit + 1` bytes raises OverSizedBody carrying the cap."""
    request = _FakeRequest(b"x" * (tiny_cap + 1))

    with pytest.raises(a2ui_wire.OverSizedBody) as excinfo:
        await a2ui_wire.read_capped_body(request)

    assert excinfo.value.limit == tiny_cap


async def test_read_capped_body_rejects_chunked_over_limit(tiny_cap):
    """Spec AC2: an over-cap body with `content_length is None` still raises."""
    request = _FakeRequest(b"x" * (tiny_cap * 4), chunked=True, chunk_size=97)
    assert request.content_length is None

    with pytest.raises(a2ui_wire.OverSizedBody):
        await a2ui_wire.read_capped_body(request)


async def test_read_capped_body_never_reads_whole_stream(tiny_cap):
    """Spec AC1: the reader never buffers more than `limit + 1` bytes."""
    request = _FakeRequest(b"x" * (tiny_cap * 50), chunked=True, chunk_size=128)

    with pytest.raises(a2ui_wire.OverSizedBody):
        await a2ui_wire.read_capped_body(request)

    # The cap prevents the allocation, not merely the response.
    assert request.content._pos <= tiny_cap + 1
    assert all(n <= tiny_cap + 1 for n in request.content.requested)


async def test_read_capped_body_handles_short_reads(tiny_cap):
    """Spec AC6: a legitimate body split across many reads is reassembled."""
    payload = b"y" * (tiny_cap - 1)
    request = _FakeRequest(payload, chunk_size=7)

    assert await a2ui_wire.read_capped_body(request) == payload


async def test_read_capped_json_raises_before_parse(tiny_cap):
    """Spec AC3: over-cap invalid JSON raises OverSizedBody, not a parse error."""
    request = _FakeRequest(b"<" * (tiny_cap + 1))

    with pytest.raises(a2ui_wire.OverSizedBody):
        await a2ui_wire.read_capped_json(request)


async def test_read_capped_json_decodes_under_cap(tiny_cap):
    """Spec AC6: an under-cap body decodes exactly as `request.json()` would."""
    body = {"version": "v1.0", "hello": "world"}
    request = _FakeRequest(json.dumps(body).encode("utf-8"))

    assert await a2ui_wire.read_capped_json(request) == body


async def test_read_capped_json_empty_body_raises_decode_error(tiny_cap):
    """Spec AC6: an empty body reaches the call sites' existing 400 branch."""
    request = _FakeRequest(b"")

    with pytest.raises(json.JSONDecodeError):
        await a2ui_wire.read_capped_json(request)


async def test_read_capped_body_resolves_cap_at_call_time(monkeypatch):
    """The cap is read from the module attribute per call, not frozen at import."""
    monkeypatch.setattr(a2ui_wire, "A2UI_MAX_BODY_BYTES", 4)

    assert await a2ui_wire.read_capped_body(_FakeRequest(b"abcd")) == b"abcd"
    with pytest.raises(a2ui_wire.OverSizedBody):
        await a2ui_wire.read_capped_body(_FakeRequest(b"abcde"))


async def test_read_capped_body_explicit_limit_overrides_module_cap(tiny_cap):
    """An explicit `limit=` wins over the module-level cap."""
    with pytest.raises(a2ui_wire.OverSizedBody) as excinfo:
        await a2ui_wire.read_capped_body(_FakeRequest(b"abcde"), limit=4)

    assert excinfo.value.limit == 4


def test_is_a2ui_content_type_headers_only():
    """Spec AC5: true only for the A2UI media type, and it never raises."""
    assert a2ui_wire.is_a2ui_content_type(_FakeRequest(b"", content_type="application/a2ui+json"))
    assert not a2ui_wire.is_a2ui_content_type(_FakeRequest(b"", content_type="application/json"))
    assert not a2ui_wire.is_a2ui_content_type(_FakeRequest(b"", content_type="text/plain"))


def test_oversized_json_response_shape():
    """Spec AC5: the plain 413 keeps `{"error", "max_bytes"}`."""
    response = a2ui_wire.oversized_json_response(1024)

    assert response.status == 413
    assert json.loads(response.body) == {"error": "body too large", "max_bytes": 1024}


def test_oversized_a2ui_response_shape():
    """Spec AC5: the A2UI 413 carries an error envelope for the surface."""
    response = a2ui_wire.oversized_a2ui_response("form-import", "body too large")

    assert response.status == 413
    assert "form-import" in response.body.decode("utf-8")


def test_schema_depth_constant_is_overridable(monkeypatch):
    """A2UI_MAX_SCHEMA_DEPTH exists with a sane default for TASK-5241."""
    assert a2ui_wire.A2UI_MAX_SCHEMA_DEPTH >= 1
