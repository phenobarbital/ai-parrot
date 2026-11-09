"""Regression coverage for Preserve Telegram topic and reply routing for every result type (TASK-5399)."""
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest
from aiogram.types import ReplyParameters

import parrot.integrations.telegram.wrapper as wrapper_mod
from parrot.integrations.parser import ChartData, ParsedResponse
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

THREAD_ID = 77
REPLY_ID = 4242
CHAT_ID = -100123


class RecordingBot:
    """Records every Bot API send; optionally fails Markdown text sends."""

    def __init__(self, fail_markdown: bool = False) -> None:
        self.fail_markdown = fail_markdown
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    async def send_message(self, **kwargs: Any) -> None:
        self.calls.append(("send_message", kwargs))
        if self.fail_markdown and kwargs.get("parse_mode"):
            raise RuntimeError("Bad Request: can't parse entities")

    async def send_photo(self, **kwargs: Any) -> None:
        self.calls.append(("send_photo", kwargs))

    async def send_document(self, **kwargs: Any) -> None:
        self.calls.append(("send_document", kwargs))

    async def send_video(self, **kwargs: Any) -> None:
        self.calls.append(("send_video", kwargs))

    async def send_audio(self, **kwargs: Any) -> None:
        self.calls.append(("send_audio", kwargs))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the rate-limit sleeps."""

    async def _sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(wrapper_mod.asyncio, "sleep", _sleep)


@pytest.fixture
def remote_download(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Dict[str, Any]:
    """Replace the bounded downloader with a deterministic double that records allowlist use and cleanup."""
    state: Dict[str, Any] = {"hosts_seen": [], "cleaned": [], "refused": []}

    def _hosts() -> List[str]:
        return ["img.example.com"]

    @asynccontextmanager
    async def _download(url: str, allowed_hosts: Optional[List[str]] = None):
        state["hosts_seen"].append(allowed_hosts)
        if "evil" in url:
            state["refused"].append(url)
            raise wrapper_mod.MediaDownloadRefused(f"host not allowed: {url}")
        path = tmp_path / f"dl_{len(state['hosts_seen'])}.png"
        path.write_bytes(b"png")
        try:
            yield path
        finally:
            path.unlink()
            state["cleaned"].append(path)

    monkeypatch.setattr(wrapper_mod, "allowed_media_hosts", _hosts)
    monkeypatch.setattr(wrapper_mod, "temp_download", _download)
    return state


def _make_wrapper(bot: RecordingBot, use_html: bool = False) -> TelegramAgentWrapper:
    wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    wrapper.bot = bot
    wrapper.config = SimpleNamespace(use_html=use_html)
    wrapper.logger = MagicMock()
    return wrapper


def _make_parsed(tmp_path: Path, text: str = "hello *world*") -> ParsedResponse:
    chart_path = tmp_path / "chart.png"
    chart_path.write_bytes(b"png")
    files: Dict[str, Path] = {}
    for name in ("pic.png", "report.pdf", "clip.mp4", "song.mp3", "blob.bin"):
        files[name] = tmp_path / name
        files[name].write_bytes(b"x")
    return ParsedResponse(
        text=text,
        images=[files["pic.png"]],
        documents=[files["report.pdf"]],
        media=[files["clip.mp4"], files["song.mp3"], files["blob.bin"]],
        image_urls=["https://img.example.com/a.png", "https://evil.example.net/b.png"],
        media_urls=["https://video.example.com/v"],
        charts=[ChartData(path=chart_path, title="Sales", chart_type="bar", format="png")],
    )


def _assert_routed(kwargs: Dict[str, Any]) -> None:
    assert kwargs["chat_id"] == CHAT_ID
    assert kwargs["message_thread_id"] == THREAD_ID
    rp = kwargs["reply_parameters"]
    assert isinstance(rp, ReplyParameters)
    assert rp.message_id == REPLY_ID
    assert rp.allow_sending_without_reply is True


async def test_telegram_queued_attachments_keep_topic_and_reply(
    tmp_path: Path, remote_download: Dict[str, Any]
) -> None:
    """Every text/chart/local+remote image/document/video/audio/fallback send carries topic and reply."""
    bot = RecordingBot()
    wrapper = _make_wrapper(bot)
    parsed = _make_parsed(tmp_path)

    await wrapper.send_parsed_to_chat(
        CHAT_ID, parsed, message_thread_id=THREAD_ID, reply_to_message_id=REPLY_ID, prefix="Job done"
    )

    methods = [name for name, _ in bot.calls]
    # text, chart, remote image (allowed), local image, document, video, audio, unknown-media fallback, media links
    assert methods.count("send_message") == 2
    assert methods.count("send_photo") == 3
    assert methods.count("send_document") == 2
    assert methods.count("send_video") == 1
    assert methods.count("send_audio") == 1
    for _, kwargs in bot.calls:
        _assert_routed(kwargs)

    first_text = bot.calls[0][1]
    assert first_text["text"].startswith("Job done")
    assert first_text["parse_mode"] == "Markdown"
    assert "https://video.example.com/v" in bot.calls[-1][1]["text"]

    # Remote images: allowlist always passed, refused host skipped, temp files cleaned up.
    assert remote_download["hosts_seen"] == [["img.example.com"], ["img.example.com"]]
    assert remote_download["refused"] == ["https://evil.example.net/b.png"]
    assert len(remote_download["cleaned"]) == 1
    assert not remote_download["cleaned"][0].exists()


async def test_text_is_chunked_and_every_chunk_keeps_destination(tmp_path: Path) -> None:
    """Long text splits into <=4096-char chunks, each routed to the same topic/reply."""
    bot = RecordingBot()
    wrapper = _make_wrapper(bot)
    long_text = "\n".join(["a" * 1000] * 10) + "\n" + "b" * 9000
    parsed = ParsedResponse(text=long_text)

    await wrapper.send_parsed_to_chat(CHAT_ID, parsed, message_thread_id=THREAD_ID, reply_to_message_id=REPLY_ID)

    texts = [kw for name, kw in bot.calls if name == "send_message"]
    assert len(texts) > 2
    assert all(len(kw["text"]) <= 4096 for kw in texts)
    assert "".join(kw["text"].replace("\n", "") for kw in texts) == long_text.replace("\n", "")
    for kw in texts:
        _assert_routed(kw)


async def test_markdown_fallback_retains_topic_when_original_deleted() -> None:
    """A parse error falls back to plain text in the same topic, with allow_sending_without_reply."""
    bot = RecordingBot(fail_markdown=True)
    wrapper = _make_wrapper(bot)
    parsed = ParsedResponse(text="broken *markdown")

    await wrapper.send_parsed_to_chat(CHAT_ID, parsed, message_thread_id=THREAD_ID, reply_to_message_id=REPLY_ID)

    assert len(bot.calls) == 2
    first, retry = bot.calls[0][1], bot.calls[1][1]
    assert first["parse_mode"] == "Markdown"
    assert retry["parse_mode"] is None
    assert "*" not in retry["text"]
    _assert_routed(first)
    _assert_routed(retry)


async def test_topic_only_routing_without_reply() -> None:
    """A topic without a reply target sets the thread and no reply parameters."""
    bot = RecordingBot()
    wrapper = _make_wrapper(bot)

    await wrapper.send_parsed_to_chat(CHAT_ID, ParsedResponse(text="hi"), message_thread_id=THREAD_ID)

    kwargs = bot.calls[0][1]
    assert kwargs["message_thread_id"] == THREAD_ID
    assert "reply_parameters" not in kwargs


async def test_existing_callers_without_routing_kwargs(tmp_path: Path, remote_download: Dict[str, Any]) -> None:
    """Positional-only callers keep the original Bot API calls (no routing keys)."""
    bot = RecordingBot()
    wrapper = _make_wrapper(bot)
    parsed = _make_parsed(tmp_path)

    await wrapper._send_attachments(CHAT_ID, parsed)
    await wrapper._send_url_photos(CHAT_ID, ["https://img.example.com/c.png"])

    assert bot.calls
    for _, kwargs in bot.calls:
        assert kwargs["chat_id"] == CHAT_ID
        assert "message_thread_id" not in kwargs
        assert "reply_parameters" not in kwargs
    assert all(hosts == ["img.example.com"] for hosts in remote_download["hosts_seen"])
    assert all(not p.exists() for p in remote_download["cleaned"])


def test_routing_parameters_are_keyword_only() -> None:
    """Routing parameters cannot be passed positionally."""
    import inspect

    for name in ("send_parsed_to_chat", "_send_attachments", "_send_url_photos"):
        params = inspect.signature(getattr(TelegramAgentWrapper, name)).parameters
        for p in ("message_thread_id", "reply_to_message_id"):
            assert params[p].kind is inspect.Parameter.KEYWORD_ONLY
            assert params[p].default is None
