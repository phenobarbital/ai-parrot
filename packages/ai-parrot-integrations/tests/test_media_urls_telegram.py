"""FEAT-601 M12 — Telegram URL images: download → send_photo → cleanup (TASK-3718)."""
from __future__ import annotations

import contextlib
from pathlib import Path
from types import SimpleNamespace
from typing import AsyncIterator, Callable, List, Tuple
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlsplit

import pytest
from aiogram.types import FSInputFile

from parrot.integrations.media_download import MediaDownloadRefused
from parrot.integrations.parser import ParsedResponse
from parrot.integrations.telegram.crew.crew_wrapper import CrewAgentWrapper
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper


def _wrapper() -> TelegramAgentWrapper:
    """Build a ``TelegramAgentWrapper`` with only the attributes the senders read."""
    w = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    w.bot = AsyncMock()
    w.logger = MagicMock()
    return w


def _crew_wrapper() -> CrewAgentWrapper:
    """Build a ``CrewAgentWrapper`` with only the attributes ``_send_response`` reads."""
    w = CrewAgentWrapper.__new__(CrewAgentWrapper)
    w.bot = AsyncMock()
    w.logger = MagicMock()
    return w


def _make_fake_temp_download(
    tmp_path: Path,
) -> Tuple[Callable[..., "contextlib.AbstractAsyncContextManager[Path]"], List[Path]]:
    """Build a fake ``temp_download``: a real temp file for allowlisted hosts, refusal otherwise.

    Mirrors the real ``media_download.temp_download`` contract (an async context manager that
    yields a real file and deletes it on exit) without any network access.

    Returns:
        A tuple of ``(fake_temp_download, created)`` where ``created`` records every temp file
        path the fake handed out, so tests can assert cleanup happened.
    """
    created: List[Path] = []

    @contextlib.asynccontextmanager
    async def _fake(url: str, *, allowed_hosts) -> AsyncIterator[Path]:
        host = (urlsplit(url).hostname or "").lower()
        if host not in {h.lower() for h in allowed_hosts}:
            raise MediaDownloadRefused(f"Host {host!r} is not allowlisted for media URL {url!r}")
        path = tmp_path / f"img-{len(created)}.jpg"
        path.write_bytes(b"fake-image-bytes")
        created.append(path)
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)

    return _fake, created


async def test_telegram_downloads_then_send_photo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """_send_attachments: allowlisted URL ⇒ send_photo with a temp file that no longer exists afterwards."""
    w = _wrapper()
    fake_temp_download, created = _make_fake_temp_download(tmp_path)
    monkeypatch.setattr("parrot.integrations.telegram.wrapper.temp_download", fake_temp_download)
    monkeypatch.setattr(
        "parrot.integrations.telegram.wrapper.allowed_media_hosts", lambda: ("example.com",)
    )
    parsed = ParsedResponse(image_urls=["https://example.com/figure.png"])

    await w._send_attachments(chat_id=123, parsed=parsed)

    w.bot.send_photo.assert_awaited_once()
    kwargs = w.bot.send_photo.call_args.kwargs
    assert kwargs["chat_id"] == 123
    assert isinstance(kwargs["photo"], FSInputFile)
    assert len(created) == 1
    assert not created[0].exists()
    w.logger.error.assert_not_called()


async def test_telegram_parsed_response_path_sends_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """_send_parsed_response (second sender) also sends URL images."""
    w = _wrapper()
    w.config = SimpleNamespace(use_html=False)
    fake_temp_download, created = _make_fake_temp_download(tmp_path)
    monkeypatch.setattr("parrot.integrations.telegram.wrapper.temp_download", fake_temp_download)
    monkeypatch.setattr(
        "parrot.integrations.telegram.wrapper.allowed_media_hosts", lambda: ("example.com",)
    )

    message = MagicMock()
    message.chat.id = 456
    parsed = ParsedResponse(image_urls=["https://example.com/figure.png"])

    await w._send_parsed_response(message, parsed)

    w.bot.send_photo.assert_awaited_once()
    kwargs = w.bot.send_photo.call_args.kwargs
    assert kwargs["chat_id"] == 456
    assert isinstance(kwargs["photo"], FSInputFile)
    assert len(created) == 1
    assert not created[0].exists()
    w.logger.error.assert_not_called()


async def test_telegram_foreign_host_refused_no_send(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Foreign host / redirect / oversize ⇒ MediaDownloadRefused logged, no send_photo, no leftover file."""
    w = _wrapper()
    fake_temp_download, created = _make_fake_temp_download(tmp_path)
    monkeypatch.setattr("parrot.integrations.telegram.wrapper.temp_download", fake_temp_download)
    monkeypatch.setattr(
        "parrot.integrations.telegram.wrapper.allowed_media_hosts", lambda: ("example.com",)
    )
    parsed = ParsedResponse(image_urls=["https://evil.example.net/figure.png"])

    await w._send_attachments(chat_id=123, parsed=parsed)

    w.bot.send_photo.assert_not_awaited()
    assert created == []
    w.logger.warning.assert_called_once()


async def test_crew_wrapper_sends_url_images(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """CrewAgentWrapper._send_response downloads and sends URL images."""
    w = _crew_wrapper()
    fake_temp_download, created = _make_fake_temp_download(tmp_path)
    monkeypatch.setattr(
        "parrot.integrations.telegram.crew.crew_wrapper.temp_download", fake_temp_download
    )
    monkeypatch.setattr(
        "parrot.integrations.telegram.crew.crew_wrapper.allowed_media_hosts",
        lambda: ("example.com",),
    )
    parsed = ParsedResponse(text="", image_urls=["https://example.com/figure.png"])

    await w._send_response(chat_id=789, parsed=parsed, sender_mention="@bob")

    w.bot.send_photo.assert_awaited_once()
    kwargs = w.bot.send_photo.call_args.kwargs
    assert kwargs["chat_id"] == 789
    assert isinstance(kwargs["photo"], FSInputFile)
    assert len(created) == 1
    assert not created[0].exists()
    w.logger.error.assert_not_called()
