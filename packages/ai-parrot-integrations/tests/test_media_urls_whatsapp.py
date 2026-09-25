"""FEAT-601 M12 — WhatsApp URL images: direct send, download fallback (TASK-3719)."""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import MagicMock

import pytest

pytest.importorskip("pywa")

from parrot.integrations.media_download import MediaDownloadRefused  # noqa: E402
from parrot.integrations.parser import ParsedResponse  # noqa: E402
from parrot.integrations.whatsapp.wrapper import WhatsAppAgentWrapper  # noqa: E402


def _wrapper() -> WhatsAppAgentWrapper:
    """Build a ``WhatsAppAgentWrapper`` with only the attributes ``_send_parsed_response`` reads."""
    w = WhatsAppAgentWrapper.__new__(WhatsAppAgentWrapper)
    w.logger = MagicMock()
    return w


async def test_whatsapp_direct_url_then_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """send_image(image=url) succeeds ⇒ no download; provider error ⇒ download path sends a local file."""
    w = _wrapper()
    client = MagicMock()
    client.send_image.side_effect = [None, Exception("provider rejected url"), None]

    fake_path = tmp_path / "fallback.jpg"
    fake_path.write_bytes(b"fake-image-bytes")

    @contextlib.asynccontextmanager
    async def _fake_temp_download(url: str, *, allowed_hosts) -> AsyncIterator[Path]:
        yield fake_path

    monkeypatch.setattr(
        "parrot.integrations.whatsapp.wrapper.temp_download", _fake_temp_download
    )
    monkeypatch.setattr(
        "parrot.integrations.whatsapp.wrapper.allowed_media_hosts", lambda: ("example.com",)
    )

    parsed = ParsedResponse(
        image_urls=[
            "https://example.com/direct.png",
            "https://example.com/needs-fallback.png",
        ]
    )

    await w._send_parsed_response("15551234567", parsed, client)

    assert client.send_image.call_count == 3
    first_call, second_call, third_call = client.send_image.call_args_list
    assert first_call.kwargs == {"to": "15551234567", "image": "https://example.com/direct.png"}
    assert second_call.kwargs == {
        "to": "15551234567",
        "image": "https://example.com/needs-fallback.png",
    }
    assert third_call.kwargs == {"to": "15551234567", "image": str(fake_path)}
    w.logger.error.assert_not_called()


async def test_whatsapp_refused_fallback_is_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider error + ``MediaDownloadRefused`` ⇒ logged, no exception raised."""
    w = _wrapper()
    client = MagicMock()
    client.send_image.side_effect = Exception("provider rejected url")

    @contextlib.asynccontextmanager
    async def _fake_temp_download(url: str, *, allowed_hosts) -> AsyncIterator[Path]:
        raise MediaDownloadRefused(f"Host not allowlisted for {url!r}")
        yield  # pragma: no cover - unreachable, keeps this an async generator

    monkeypatch.setattr(
        "parrot.integrations.whatsapp.wrapper.temp_download", _fake_temp_download
    )
    monkeypatch.setattr(
        "parrot.integrations.whatsapp.wrapper.allowed_media_hosts", lambda: ("example.com",)
    )

    parsed = ParsedResponse(image_urls=["https://evil.example.net/figure.png"])

    await w._send_parsed_response("15551234567", parsed, client)

    client.send_image.assert_called_once()
    w.logger.warning.assert_called()
    w.logger.error.assert_not_called()
