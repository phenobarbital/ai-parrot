"""FEAT-886 M17 — BotManager turn-persistence lifecycle and durable-memory attachment (real manager, real bus)."""
from __future__ import annotations

import inspect
import uuid

import pytest
from aiohttp import web
from navigator_eventbus import EventBus

from parrot.bots.base import BaseBot
from parrot.clients.base import AbstractClient
from parrot.manager.manager import BotManager
from parrot.memory import InMemoryConversation
from parrot.storage import ChatStorage
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.hydration import ChatStorageHydrationSource
from parrot.storage.turn_bus import setup_turn_persistence, shutdown_turn_persistence

pytestmark = pytest.mark.skipif(
    "transport" not in inspect.signature(EventBus.__init__).parameters,
    reason="navigator-eventbus >= 0.4.0 required (EventBus(transport=...))",
)


class _HotTier(InMemoryConversation):
    """Stand-in for the Redis hot tier (the one external service): same upsert contract."""

    async def upsert_turn(self, user_id, session_id, turn, chatbot_id=None):
        history = await self.get_history(user_id, session_id, chatbot_id) or await self.create_history(
            user_id, session_id, chatbot_id=chatbot_id)
        history.turns = [t for t in history.turns if t.turn_id != turn.turn_id] + [turn]
        await self.update_history(history)


class _Client(AbstractClient):
    client_type = "stub"
    supported_models = ["stub"]

    def __init__(self, **kwargs):
        kwargs.setdefault("model", "stub")
        super().__init__(**kwargs)

    async def get_client(self):
        return self

    async def _ensure_client(self):
        return self

    async def ask(self, *a, **kw):
        raise NotImplementedError

    async def ask_stream(self, *a, **kw):
        yield ""

    async def resume(self, *a, **kw):
        raise NotImplementedError

    async def invoke(self, *a, **kw):
        raise NotImplementedError


def _manager() -> BotManager:
    return BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=True,
                      enable_swagger_api=False)


def _bot(name: str = "alpha", **kw) -> BaseBot:
    return BaseBot(name=name, llm=_Client(), memory_type="memory", injection_detection=False, **kw)


@pytest.fixture
async def storage(tmp_path):
    backend = ConversationSQLiteBackend(path=str(tmp_path / "conv.db"))
    await backend.initialize()
    return ChatStorage(redis_conversation=_HotTier(), dynamodb=backend)


@pytest.fixture
def wired(monkeypatch, storage, tmp_path):
    """Real manager seams: the ChatStorage factory and the bus (the external service) are injected."""
    calls = {"shutdown": [], "order": []}
    bus = EventBus(transport="memory", outbox=str(tmp_path / "outbox.db"))

    async def _setup(cs, **kw):
        return await setup_turn_persistence(cs, bus=bus)

    async def _shutdown(handle):
        calls["shutdown"].append(handle)
        calls["order"].append("bus")
        await shutdown_turn_persistence(handle)

    original_close = storage.close

    async def _close():
        calls["order"].append("storage")
        await original_close()

    monkeypatch.setattr(storage, "close", _close)
    monkeypatch.setattr("parrot.manager.manager.ChatStorage", lambda: storage)
    monkeypatch.setattr("parrot.manager.manager.setup_turn_persistence", _setup)
    monkeypatch.setattr("parrot.manager.manager.shutdown_turn_persistence", _shutdown)
    return calls


async def test_registry_only_turn_persistence(wired):
    app, mgr = web.Application(), _manager()
    mgr.setup_registry_only(app, turn_persistence=True)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        assert app["turn_persistence"].subscription_ids
    finally:
        await runner.cleanup()
    assert len(wired["shutdown"]) == 1
    assert wired["order"] == ["bus", "storage"]  # the bus stops before ChatStorage closes


async def test_flag_off_touches_nothing(wired):
    app, mgr = web.Application(), _manager()
    mgr.setup_registry_only(app)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        assert "turn_persistence" not in app and "chat_storage" not in app
    finally:
        await runner.cleanup()
    assert wired["shutdown"] == []


async def test_add_bot_attaches_durable_memory(wired):
    app, mgr = web.Application(), _manager()
    early = _bot("early")
    mgr.add_bot(early)  # registered before the bus exists
    assert early.turn_publisher is None
    own = object.__new__(type("_Pub", (), {"publish": lambda self, e: None}))
    mgr.setup_registry_only(app, turn_persistence=True)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        handle = app["turn_persistence"]
        assert early.turn_publisher is handle.publisher  # attached by the post-start sweep
        late = _bot("late")
        mgr.add_bot(late)
        assert late.turn_publisher is handle.publisher
        assert isinstance(late.hydration_source, ChatStorageHydrationSource)
        assert late.sequence_allocator is not None
        keeps = _bot("keeps", turn_publisher=own)
        mgr.add_bot(keeps)
        assert keeps.turn_publisher is own  # an injected collaborator wins
        mgr.add_bot(late)  # idempotent: no second cleaner
        assert len(app["chat_storage"]._memory_cleaners) == 3
    finally:
        await runner.cleanup()


async def test_no_persistence_means_no_attachment(wired):
    app, mgr = web.Application(), _manager()
    mgr.setup_registry_only(app)
    bot = _bot()
    mgr.add_bot(bot)
    assert bot.turn_publisher is None and bot.hydration_source is None and bot.sequence_allocator is None


async def test_conversation_delete_clears_bot_working_memory(wired, storage):
    app, mgr = web.Application(), _manager()
    mgr.setup_registry_only(app, turn_persistence=True)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        bot = _bot("alpha", chatbot_id="uuid-9")
        bot.conversation_memory = InMemoryConversation()
        mgr.add_bot(bot)
        await bot.conversation_memory.create_history("u", "s", chatbot_id=bot.memory_key_id)
        await storage.delete_conversation("u", "s", agent_id=bot.name)
        assert await bot.conversation_memory.get_history("u", "s", chatbot_id=bot.memory_key_id) is None
    finally:
        await runner.cleanup()


async def test_bus_start_failure_does_not_block_startup(monkeypatch, caplog, storage):
    async def _boom(cs, **kw):
        raise RuntimeError("outbox unset")

    monkeypatch.setattr("parrot.manager.manager.ChatStorage", lambda: storage)
    monkeypatch.setattr("parrot.manager.manager.setup_turn_persistence", _boom)
    app, mgr = web.Application(), _manager()
    mgr.setup_registry_only(app, turn_persistence=True)
    runner = web.AppRunner(app)
    await runner.setup()  # startup finishes
    try:
        assert "turn_persistence" not in app
        assert any(r.levelname == "ERROR" and "Turn persistence not started" in r.getMessage()
                   for r in caplog.records)
        bot = _bot()
        mgr.add_bot(bot)
        assert bot.turn_publisher is None and bot.hydration_source is None
    finally:
        await runner.cleanup()


async def test_on_shutdown_stops_bus_before_closing_storage(wired, storage):
    mgr = _manager()
    app = {}
    handle = await setup_turn_persistence(storage, bus=EventBus(transport="memory"))
    app["turn_persistence"] = handle
    app["chat_storage"] = storage

    await mgr.on_shutdown(app)
    assert wired["order"][:2] == ["bus", "storage"]


async def test_per_user_bots_are_attached_on_build_and_on_retrieval(wired, monkeypatch):
    """Per-user bots (built per session, cached on it) must publish too: AgentTalk no longer writes."""
    app, mgr = web.Application(), _manager()
    mgr.setup_registry_only(app, turn_persistence=True)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        handle = app["turn_persistence"]
        built = _bot("user-bot")
        calls = {"n": 0}

        class _Basic:
            def __new__(cls, **kw):
                calls["n"] += 1
                return built

        monkeypatch.setattr("parrot.manager.manager.BasicBot", _Basic)

        class _Model:
            chatbot_id = "ub-1"
            prompt_config = {}

            def to_bot_kwargs(self):
                return {}

        async def _fetch(user_id, cid):
            return _Model()

        monkeypatch.setattr(mgr, "_fetch_user_bot_model", _fetch)
        monkeypatch.setattr(mgr, "_apply_prompt_config", lambda bot, cfg: None)

        async def _configure(app=None):
            return None

        monkeypatch.setattr(built, "configure", _configure)
        session = {"user_id": "u1"}
        request = type("R", (), {"session": session})()
        import sys
        import types as _t

        fake = _t.ModuleType("navigator_session")

        async def _get_session(req):
            return session

        fake.get_session = _get_session
        monkeypatch.setitem(sys.modules, "navigator_session", fake)

        bot = await mgr.get_user_bot(request, "ub-1")
        assert bot is built and bot.turn_publisher is handle.publisher  # attached on build
        assert isinstance(bot.hydration_source, ChatStorageHydrationSource)
        # a bot cached on the session BEFORE the bus existed is attached on retrieval
        bot.turn_publisher = None
        bot._durable_memory_attached = False
        again = await mgr.get_user_bot(request, "ub-1")
        assert again is built and calls["n"] == 1 and again.turn_publisher is handle.publisher
    finally:
        await runner.cleanup()
