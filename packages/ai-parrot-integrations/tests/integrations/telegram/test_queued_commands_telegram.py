"""Regression coverage for Preserve Telegram topic and reply routing for every result type (TASK-5399)."""

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest
from aiogram.types import ReplyParameters

import parrot.integrations.telegram.wrapper as wrapper_mod
from parrot.integrations.core.queued import JobNotice, SubmitOutcome, queued_command
from parrot.integrations.manager import IntegrationBotManager
from parrot.integrations.parser import ChartData, ParsedResponse
from parrot.integrations.telegram.decorators import discover_telegram_commands
from parrot.integrations.telegram.manager import TelegramBotManager
from parrot.integrations.telegram.queued_commands import TelegramQueuedCommands
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


class _QueuedAgent:
    """Small agent fixture exposing one queued command and its Telegram alias."""

    @queued_command("pr_review", "Review a pull request", aliases=("pr-review",))
    async def review(self, value: str = "") -> str:
        """Return a deterministic queued result."""

        return value


class _MessageRegistry:
    """Capture aiogram registrations without constructing a live router."""

    def __init__(self) -> None:
        self.handlers: List[Any] = []

    def register(self, handler: Any, *_filters: Any) -> None:
        """Record one registered message handler."""

        self.handlers.append(handler)


class _Router:
    """Minimal router double used to inspect command registration."""

    def __init__(self) -> None:
        self.message = _MessageRegistry()


class _QueuedMessage:
    """Message double retaining replies and Telegram routing fields."""

    def __init__(self, text: str = "/pr_review 42") -> None:
        self.text = text
        self.chat = SimpleNamespace(id=CHAT_ID)
        self.from_user = SimpleNamespace(id=88123)
        self.message_id = REPLY_ID
        self.message_thread_id = THREAD_ID
        self.is_topic_message = True
        self.answers: List[str] = []

    async def answer(self, text: str) -> None:
        """Record an immediate command response."""

        self.answers.append(text)


class _QueuedWrapper:
    """Wrapper double supplying the adapter's verified wrapper contract."""

    def __init__(self) -> None:
        self.config = SimpleNamespace(name="test-bot")
        self.bot = RecordingBot()
        self.sent: List[Dict[str, Any]] = []

    def _is_authorized(self, _chat_id: int) -> bool:
        """Authorize the test chat."""

        return True

    async def _check_authentication(self, _message: Any) -> bool:
        """Accept the test user."""

        return True

    def _get_user_session(self, _message: Any) -> Any:
        """Return the requester's display identity."""

        return SimpleNamespace(display_name="Clicker")

    async def send_parsed_to_chat(self, chat_id: int, parsed: ParsedResponse, **kwargs: Any) -> None:
        """Capture background delivery routing."""

        self.sent.append({"chat_id": chat_id, "parsed": parsed, **kwargs})


class _RecordingService:
    """Service double that captures the command delivery closure."""

    def __init__(self) -> None:
        self.delivery: Any = None
        self.requester: Any = None

    async def submit(self, _command: Any, _args: str, requester: Any, delivery: Any) -> SubmitOutcome:
        """Return an accepted job without completing it inline."""

        self.requester = requester
        self.delivery = delivery
        return SubmitOutcome(status="accepted", job_id="job-1", label="review", message="")

    async def stop(self) -> None:
        """Satisfy the adapter shutdown contract."""

        return None


async def test_telegram_registers_queued_and_job_commands() -> None:
    """Canonical commands enter menus while aliases remain routing-only."""

    adapter = TelegramQueuedCommands(_QueuedWrapper(), [])
    command = _QueuedAgent().review
    from parrot.integrations.core.queued import discover_queued_commands

    adapter.commands = discover_queued_commands(_QueuedAgent())
    router = _Router()
    entries = adapter.register(router)  # type: ignore[arg-type]

    assert [name for name, _description in entries] == ["pr_review", "jobs", "job_status", "job_cancel"]
    assert len(router.message.handlers) == 4
    assert command is not None


async def test_telegram_ack_then_reply_in_topic() -> None:
    """The immediate acknowledgement precedes captured topic/reply delivery."""

    wrapper = _QueuedWrapper()
    from parrot.integrations.core.queued import discover_queued_commands

    adapter = TelegramQueuedCommands(wrapper, discover_queued_commands(_QueuedAgent()))
    service = _RecordingService()
    adapter.service = service  # type: ignore[assignment]
    router = _Router()
    adapter.register(router)  # type: ignore[arg-type]
    message = _QueuedMessage()

    await router.message.handlers[0](message)
    assert message.answers == [
        "⏳ Accepted — job `job-1`: review.\nI'll post the result here. Track it with /job_status job-1"
    ]
    await service.delivery(
        JobNotice(job_id="job-1", command="pr_review", label="review", status="completed", result="done")
    )

    assert service.requester.user_id == "88123"
    assert wrapper.sent[0]["chat_id"] == CHAT_ID
    assert wrapper.sent[0]["message_thread_id"] == THREAD_ID
    assert wrapper.sent[0]["reply_to_message_id"] == REPLY_ID
    assert wrapper.sent[0]["parsed"].text == "done"


def test_telegram_discovery_skips_queued_methods() -> None:
    """Queued methods are not also registered as inline Telegram commands."""

    assert discover_telegram_commands(_QueuedAgent()) == []


async def test_telegram_function_refuses_queued_method() -> None:
    """Generic method paths refuse queued methods without invoking them."""

    wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    wrapper.agent = _QueuedAgent()
    wrapper.config = SimpleNamespace()
    wrapper.logger = MagicMock()
    wrapper._is_authorized = lambda _chat_id: True

    async def authenticated(_message: Any) -> bool:
        return True

    wrapper._check_authentication = authenticated
    message = _QueuedMessage("/function review")
    await wrapper.handle_function(message)
    assert message.answers == ["Use /pr_review — it runs in the background."]

    message = _QueuedMessage("/call review")
    await wrapper._execute_agent_method(message, "review", "")
    assert message.answers == ["Use /pr_review — it runs in the background."]


class _CloseWrapper:
    """Record wrapper shutdown before a bot session closes."""

    def __init__(self, events: List[str]) -> None:
        self.events = events

    async def close(self) -> None:
        """Record wrapper closure."""

        self.events.append("wrapper")
        raise RuntimeError("expected close failure")


class _CloseSession:
    """Record session closure even after wrapper cleanup fails."""

    def __init__(self, events: List[str]) -> None:
        self.events = events

    async def close(self) -> None:
        """Record session closure."""

        self.events.append("session")


async def test_managers_call_wrapper_close_before_session_close() -> None:
    """Both manager shutdown paths isolate wrapper errors before session closure."""

    for manager_type, bot_key in ((TelegramBotManager, "bots"), (IntegrationBotManager, "telegram_bots")):
        events: List[str] = []
        manager = manager_type.__new__(manager_type)
        manager.logger = MagicMock()
        setattr(
            manager, bot_key, {"test": (SimpleNamespace(session=_CloseSession(events)), None, _CloseWrapper(events))}
        )
        manager._polling_tasks = []
        if manager_type is IntegrationBotManager:
            manager.msteams_bots = {}
            manager.whatsapp_bots = {}
            manager.slack_bots = {}
            manager._devloop_services = {}
            manager._devloop_redis = {}
            manager.msagentsdk_bots = {}
            manager.a2a_bots = {}
            manager.msagent_bots = {}
            manager._a2a_runners = []
            manager.matrix_crew = None
            manager.human_manager = None
            manager._human_redis = None
        await manager.shutdown()
        assert events == ["wrapper", "session"]
