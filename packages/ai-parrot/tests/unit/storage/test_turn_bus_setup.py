"""FEAT-886 M10 — turn bus setup: validation, wiring, dead letters, replay (real memory bus, real SQLite)."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import navigator_eventbus
import pytest
from navigator_eventbus import EventBus, EventEnvelope

from parrot import conf
from parrot.core.events.lifecycle import TraceContext
from parrot.core.events.lifecycle.events.memory import TurnCompletedEvent
from parrot.memory import ConversationTurn
from parrot.memory.persistence import TURN_COMPLETED_TOPIC, TurnPresentation
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.chat import ChatStorage
from parrot.storage.errors import StorageUnavailableError
from parrot.storage.turn_bus import (
    SqliteDeadLetterStore,
    TurnPersistence,
    _make_dlq_callback,
    replay_dead_letters,
    setup_turn_persistence,
    shutdown_turn_persistence,
)

pytestmark = pytest.mark.skipif(
    not hasattr(navigator_eventbus, "SqliteOutbox"),
    reason="navigator-eventbus >= 0.4.0 required (stale environment: run `uv sync`)")

USER, AGENT = "u1", "agent-a"


@pytest.fixture
async def backend(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "cold.db"))
    await b.initialize()
    yield b
    await b.close()


@pytest.fixture
def chat_storage(backend):
    storage = ChatStorage(redis_conversation=None, dynamodb=backend)  # hot tier absent: store_turn skips it
    storage._initialized = True
    return storage


def _event(turn_id: str = "t1", session: str = "s1") -> TurnCompletedEvent:
    turn = ConversationTurn(turn_id=turn_id, user_id=USER, user_message="hi", assistant_response="hello",
                            timestamp=datetime(2026, 11, 1, tzinfo=timezone.utc), sequence=1, chatbot_id="bot")
    return TurnCompletedEvent(trace_context=TraceContext.new_root(), agent_name=AGENT, chatbot_id="bot",
                              user_id=USER, session_id=session, turn=turn.to_dict(),
                              presentation=TurnPresentation(output="hello").model_dump())


async def _eventually(predicate, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(0.02)
    return False


def _memory_bus(tmp_path, holder=None) -> EventBus:
    kwargs = dict(transport="memory", outbox=str(tmp_path / "outbox.db"), retry_attempts=3, retry_base_delay=0.0)
    if holder is not None:
        kwargs["on_dlq"] = _make_dlq_callback(holder)
    return EventBus(**kwargs)


def test_setup_requires_writable_outbox(monkeypatch, tmp_path):
    from parrot.storage import turn_bus

    monkeypatch.setattr(conf, "PARROT_TURN_BUS_REDIS_URL", "redis://localhost:6399/0", raising=False)
    for bad in (None, str(tmp_path / "missing"), str(tmp_path / "a-file")):
        if bad and bad.endswith("a-file"):
            (tmp_path / "a-file").write_text("x")
        monkeypatch.setattr(conf, "PARROT_TURN_BUS_OUTBOX_DIR", bad, raising=False)
        with pytest.raises(RuntimeError, match="PARROT_TURN_BUS_OUTBOX_DIR"):
            turn_bus._build_bus({})
    if os.geteuid() != 0:
        ro = tmp_path / "ro"
        ro.mkdir()
        ro.chmod(0o500)
        monkeypatch.setattr(conf, "PARROT_TURN_BUS_OUTBOX_DIR", str(ro), raising=False)
        try:
            with pytest.raises(RuntimeError, match="PARROT_TURN_BUS_OUTBOX_DIR"):
                turn_bus._build_bus({})
        finally:
            ro.chmod(0o700)


def test_setup_requires_redis_url(monkeypatch, tmp_path):
    from parrot.storage import turn_bus

    monkeypatch.setattr(conf, "PARROT_TURN_BUS_REDIS_URL", None, raising=False)
    monkeypatch.setattr(conf, "PARROT_TURN_BUS_OUTBOX_DIR", str(tmp_path), raising=False)
    with pytest.raises(RuntimeError, match="PARROT_TURN_BUS_REDIS_URL"):
        turn_bus._build_bus({})


async def test_bus_uses_isolated_stream_prefix(monkeypatch, tmp_path):
    from parrot.storage import turn_bus

    monkeypatch.setattr(conf, "PARROT_TURN_BUS_REDIS_URL", "redis://localhost:6399/0", raising=False)
    monkeypatch.setattr(conf, "PARROT_TURN_BUS_OUTBOX_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(conf, "PARROT_TURN_BUS_CHANNEL_PREFIX", "test:turns:", raising=False)
    bus = turn_bus._build_bus({})
    try:
        backend = bus.core._backend
        assert type(backend).__name__ == "RedisStreamsBackend"
        assert backend.stream_prefix == "test:turns:"  # NOT the library default "evb:stream:"
        outbox_path = Path(str(bus.core._outbox._path))
        assert outbox_path.parent == Path(tmp_path) and outbox_path.name.endswith(f"-{os.getpid()}.db")
        assert bus.core._publish_only is False if hasattr(bus.core, "_publish_only") else True
    finally:
        await bus.close()


async def test_wiring_stores_published_turn(chat_storage, backend, tmp_path):
    handle = await setup_turn_persistence(chat_storage, bus=_memory_bus(tmp_path))
    try:
        assert len(handle.subscription_ids) == 2
        await handle.publisher.publish(_event())

        async def stored():
            return bool(await backend.query_turns(USER, AGENT, "s1"))

        assert await _eventually(stored)
        assert [t["turn_id"] for t in await backend.query_turn_window(USER, AGENT, "s1", 5)] == ["t1"]
    finally:
        await shutdown_turn_persistence(handle)


async def test_deletion_event_reaches_cleanup_handler(chat_storage, backend, tmp_path):
    handle = await setup_turn_persistence(chat_storage, bus=_memory_bus(tmp_path))
    cleaned = []

    async def cleaner(user, agent, session):
        cleaned.append((user, agent, session))

    chat_storage.register_memory_cleaner(cleaner)
    try:
        await chat_storage.delete_conversation(USER, "s1", AGENT)
        # once by the delete itself, once more by the handler that consumed the published deletion event

        async def twice():
            return len(cleaned) >= 2

        assert await _eventually(twice)
    finally:
        await shutdown_turn_persistence(handle)


async def test_retry_exhaustion_lands_in_dead_letters(backend, tmp_path):
    class _Down(ConversationSQLiteBackend):
        async def put_turn(self, *a, **kw):
            raise StorageUnavailableError("down")

    down = _Down(path=str(tmp_path / "down.db"))
    await down.initialize()
    storage = ChatStorage(redis_conversation=None, dynamodb=down)
    storage._initialized = True
    holder: dict = {}
    store = SqliteDeadLetterStore(tmp_path / "dead.db")
    holder["dlq"] = store
    handle = await setup_turn_persistence(storage, bus=_memory_bus(tmp_path, holder))
    handle.dlq = store
    try:
        await handle.publisher.publish(_event("dead-1"))

        async def dead():
            return bool(await store.pending())

        assert await _eventually(dead)
        [env] = await store.pending()
        assert env.event_id == "dead-1"
    finally:
        await shutdown_turn_persistence(handle)
        await down.close()


async def test_replay_republishes_once_and_never_resurrects_a_deleted_session(chat_storage, backend, tmp_path):
    store = SqliteDeadLetterStore(tmp_path / "dead.db")
    handle = await setup_turn_persistence(chat_storage, bus=_memory_bus(tmp_path))
    handle.dlq = store
    try:
        live = EventEnvelope(topic=TURN_COMPLETED_TOPIC, event_id="t-live",
                             payload=_event("t-live", "s-live").to_dict())
        dead = EventEnvelope(topic=TURN_COMPLETED_TOPIC, event_id="t-dead",
                             payload=_event("t-dead", "s-dead").to_dict())
        await store.add(live, attempts=3, error=RuntimeError("x"), subscriber_id="sub")
        await store.add(dead, attempts=3, error=RuntimeError("x"), subscriber_id="sub")
        await backend.put_tombstone(USER, AGENT, "s-dead")
        assert await replay_dead_letters(handle) == 2
        assert await replay_dead_letters(handle) == 0  # exactly once

        async def live_stored():
            return bool(await backend.query_turns(USER, AGENT, "s-live"))

        assert await _eventually(live_stored)
        await asyncio.sleep(0.2)
        assert await backend.query_turns(USER, AGENT, "s-dead") == []
    finally:
        await shutdown_turn_persistence(handle)


async def test_replay_requires_a_dead_letter_store(chat_storage, tmp_path):
    handle = await setup_turn_persistence(chat_storage, bus=_memory_bus(tmp_path))
    try:
        with pytest.raises(RuntimeError):
            await replay_dead_letters(handle)
    finally:
        await shutdown_turn_persistence(handle)


async def test_shutdown_is_idempotent_and_keeps_files(chat_storage, tmp_path):
    handle = await setup_turn_persistence(chat_storage, bus=_memory_bus(tmp_path))
    await shutdown_turn_persistence(handle)
    await shutdown_turn_persistence(handle)
    assert handle.subscription_ids == [] and (tmp_path / "outbox.db").exists()
    assert isinstance(handle, TurnPersistence)


async def test_replacement_worker_delivers_the_turn_a_dead_worker_outboxed(backend, chat_storage, tmp_path):
    """Process A outboxes a turn and dies before relay; process B (other PID) delivers it exactly once."""
    import socket
    from navigator_eventbus.outbox import SqliteOutbox
    from parrot.storage.turn_bus import recover_abandoned_outboxes

    dead_file = tmp_path / f"{socket.gethostname()}-424242.db"
    dead = SqliteOutbox(dead_file)
    envelope = EventEnvelope(topic=TURN_COMPLETED_TOPIC, event_id="orphan-1", payload=_event("orphan-1").to_dict())
    await dead.append(envelope)
    await dead.close()  # the owner "died": its lock is released, the row is still pending

    handle = await setup_turn_persistence(chat_storage, bus=_memory_bus(tmp_path))
    try:
        assert await recover_abandoned_outboxes(handle.bus, tmp_path, own_pid=os.getpid()) == 1

        async def stored():
            return bool(await backend.query_turns(USER, AGENT, "s1"))

        assert await _eventually(stored)
        assert len(await backend.query_turns(USER, AGENT, "s1")) == 1
        assert not dead_file.exists()  # drained and removed
        assert await recover_abandoned_outboxes(handle.bus, tmp_path, own_pid=os.getpid()) == 0
    finally:
        await shutdown_turn_persistence(handle)


async def test_live_workers_outbox_is_never_drained(chat_storage, tmp_path):
    import socket
    from navigator_eventbus.outbox import SqliteOutbox
    from parrot.storage.turn_bus import recover_abandoned_outboxes

    live_file = tmp_path / f"{socket.gethostname()}-777777.db"
    live = SqliteOutbox(live_file)  # holds the exclusive lock, like a running worker
    await live.append(EventEnvelope(topic=TURN_COMPLETED_TOPIC, event_id="mine", payload=_event("mine").to_dict()))
    handle = await setup_turn_persistence(chat_storage, bus=_memory_bus(tmp_path))
    try:
        assert await recover_abandoned_outboxes(handle.bus, tmp_path, own_pid=os.getpid()) == 0
        assert live_file.exists()
    finally:
        await shutdown_turn_persistence(handle)
        await live.close()
