"""FEAT-886 integration suite: bot -> bus -> ChatStorage -> hydration (spec §4).

Real objects at every join: ``BaseBot`` round -> ``BusTurnPublisher`` -> ``EventBus(transport="memory")`` ->
``ChatStorage.handle_turn_completed`` -> ``ConversationSQLiteBackend`` -> ``ChatStorageHydrationSource`` -> a second
bot with empty working memory. Doubles: the offline LLM client and the Redis hot-tier stand-in.
"""
from __future__ import annotations

import asyncio
import inspect
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

import pytest
from navigator_eventbus import EventBus

from parrot.bots.base import BaseBot
from parrot.clients.base import AbstractClient
from parrot.memory import InMemoryConversation
from parrot.memory.hydration import HydrationUnavailableError, LocalSequenceAllocator, SessionDeletedError
from parrot.memory.persistence import TURN_COMPLETED_TOPIC
from parrot.models import AIMessage
from parrot.models.basic import CompletionUsage, ToolCall
from parrot.storage import ChatStorage
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.errors import ConversationDeletedError, StorageWriteError
from parrot.storage.hydration import ChatStorageHydrationSource
from parrot.storage.turn_bus import setup_turn_persistence, shutdown_turn_persistence

pytestmark = pytest.mark.skipif(
    "transport" not in inspect.signature(EventBus.__init__).parameters,
    reason="navigator-eventbus >= 0.4.0 required (EventBus(transport='memory'))",
)
USER, SESSION, AGENT, KEY = "u1", "s1", "alpha", "uuid-alpha"


class RecordingClient(AbstractClient):
    """Offline client: records kwargs; ``ask_stream`` can fail or hang after N chunks."""

    client_type = "recording"
    supported_models = ["stub"]

    def __init__(self, fail_after: Optional[int] = None, hang_after: Optional[int] = None, **kwargs: Any) -> None:
        kwargs.setdefault("model", "stub")
        super().__init__(**kwargs)
        self.calls: List[Dict[str, Any]] = []
        self.fail_after, self.hang_after = fail_after, hang_after

    async def get_client(self) -> "RecordingClient":
        return self

    async def _ensure_client(self) -> "RecordingClient":
        return self

    def _msg(self, prompt: str) -> AIMessage:
        return AIMessage(
            input=prompt, output="reply", model="stub", provider="stub", turn_id=str(uuid.uuid4()),
            usage=CompletionUsage(prompt_tokens=3, completion_tokens=5, total_tokens=8, estimated_cost=0.42),
            tool_calls=[ToolCall(id="t1", name="lookup", arguments={"q": "x"}, result="42", execution_time=0.5)],
        )

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> AIMessage:
        self.calls.append({"prompt": prompt, **kwargs})
        return self._msg(prompt)

    async def ask_stream(self, prompt: str, **kwargs: Any):
        self.calls.append({"prompt": prompt, "stream": True, **kwargs})
        for i, chunk in enumerate(("par", "tial")):
            if self.fail_after is not None and i >= self.fail_after:
                raise RuntimeError("boom")
            if self.hang_after is not None and i >= self.hang_after:
                await asyncio.sleep(60)
            yield chunk
        yield self._msg(prompt)

    async def resume(self, *a: Any, **kw: Any):
        raise NotImplementedError

    async def invoke(self, *a: Any, **kw: Any):
        raise NotImplementedError


class _HotTier(InMemoryConversation):
    """Stand-in for the Redis hot tier — the one external service that cannot run here."""

    async def upsert_turn(self, user_id, session_id, turn, chatbot_id=None):
        history = await self.get_history(user_id, session_id, chatbot_id) or await self.create_history(
            user_id, session_id, chatbot_id=chatbot_id)
        turns = list(history.turns)
        for i, old in enumerate(turns):
            if old.turn_id == turn.turn_id:
                turns[i] = turn
                break
        else:
            turns.append(turn)
        history.turns = turns
        await self.update_history(history)


async def _eventually(predicate: Callable[[], Awaitable[bool]], timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not await predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition not reached"
        await asyncio.sleep(0.01)


@dataclass
class Stack:
    backend: ConversationSQLiteBackend
    storage: ChatStorage
    bus: Any
    handle: Any
    dead_letters: List[Any]
    envelopes: List[Any]
    make_bot: Callable[..., Awaitable[BaseBot]]
    handler_done: asyncio.Event = field(default_factory=asyncio.Event)

    async def stored_turns(self, agent_id: str = AGENT, session: str = SESSION) -> List[dict]:
        return await self.backend.query_turns(USER, agent_id, session, limit=50, newest_first=False)

    async def hot_ids(self, session: str = SESSION) -> List[str]:
        h = await self.storage._redis.get_history(USER, session, chatbot_id=AGENT)
        return [t.turn_id for t in h.turns] if h else []

    async def has_turns(self, n: int, session: str = SESSION) -> bool:
        return len(await self.stored_turns(session=session)) >= n


async def _build(tmp_path, gate: Optional[asyncio.Event] = None) -> Stack:
    backend = ConversationSQLiteBackend(path=str(tmp_path / "conv.db"))
    await backend.initialize()
    storage = ChatStorage(redis_conversation=_HotTier(), dynamodb=backend)
    dead: List[Any] = []
    envelopes: List[Any] = []
    done = asyncio.Event()

    if gate is not None:
        real = storage.handle_turn_completed

        async def gated(envelope):
            await gate.wait()
            try:
                await real(envelope)
            finally:
                done.set()

        storage.handle_turn_completed = gated  # subscribed by setup_turn_persistence below

    async def _on_dlq(envelope, *, attempts, error, subscriber_id):
        dead.append((envelope, attempts, error))

    bus = EventBus(transport="memory", on_dlq=_on_dlq, retry_attempts=3, retry_base_delay=0.0,
                   outbox=str(tmp_path / "outbox.db"))

    async def record(envelope):
        envelopes.append(envelope)

    bus.core.subscribe(TURN_COMPLETED_TOPIC, record)
    handle = await setup_turn_persistence(storage, bus=bus)
    allocator = LocalSequenceAllocator()

    async def make_bot(*, name=AGENT, chatbot_id=KEY, memory=None, client=None, source=None, **kw) -> BaseBot:
        bot = BaseBot(name=name, chatbot_id=chatbot_id, llm=client or RecordingClient(), memory_type="memory",
                      injection_detection=False, turn_publisher=handle.publisher,
                      hydration_source=source or ChatStorageHydrationSource(backend),
                      sequence_allocator=allocator, **kw)
        await bot.configure()
        bot.conversation_memory = memory or InMemoryConversation()
        return bot

    stack = Stack(backend, storage, bus, handle, dead, envelopes, make_bot, done)
    return stack


@pytest.fixture
async def stack(tmp_path):
    s = await _build(tmp_path)
    yield s
    await shutdown_turn_persistence(s.handle)
    await s.storage.close()


async def _ask(bot: BaseBot, text: str = "hello", session: str = SESSION, **kw) -> AIMessage:
    return await bot.ask(text, user_id=USER, session_id=session, use_vector_context=False, **kw)


async def test_turn_round_trip_bus_to_storage(stack):
    """bot round -> publisher -> bus -> ChatStorage; the stored turn has tool results, usage and tenant."""
    bot = await stack.make_bot()
    await _ask(bot, tenant="acme")
    await _eventually(lambda: stack.has_turns(1))
    row = (await stack.stored_turns())[0]
    inv = row["tool_invocations"][0]
    assert inv["tool_name"] == "lookup" and inv["output"] == "42" and inv["elapsed_ms"] is not None
    pres = row["presentation"]
    assert pres["usage"]["total_tokens"] == 8 and pres["cost_usd"] == 0.42
    assert pres["model"] == "stub" and pres["provider"] == "stub"
    assert row["schema_version"] == 2 and row["chatbot_id"] == KEY
    assert await stack.stored_turns(agent_id=KEY) == []  # keyed by agent NAME, not memory_key_id
    assert (await stack.backend.query_turn_window(USER, AGENT, SESSION, 5))[0]["sequence"] >= 1


async def test_ask_second_round_sees_first_round_without_injected_memory(stack):
    """spec §5 'AgentTalk mismatch fixed': the second round of ONE bot reads what the first wrote."""
    bot = await stack.make_bot()
    await _ask(bot, "first question")
    await _ask(bot, "second question")
    assert any("first question" in m.content for m in bot.get_client().calls[-1]["history"])


async def test_retry_then_dlq(stack):
    """failing backend: three attempts, then the envelope is in the DLQ; replay stores exactly one turn."""
    calls = {"n": 0}
    real_put = stack.backend.put_turn

    async def failing_put(*a, **kw):
        calls["n"] += 1
        raise StorageWriteError("disk full")

    stack.backend.put_turn = failing_put
    bot = await stack.make_bot()
    response = await _ask(bot)

    async def dead():
        return len(stack.dead_letters) == 1

    await _eventually(dead)
    assert calls["n"] == 3  # retry_attempts
    envelope = stack.dead_letters[0][0]
    stack.backend.put_turn = real_put
    await stack.storage.handle_turn_completed(envelope)  # replay
    await stack.storage.handle_turn_completed(envelope)  # at-least-once duplicate
    rows = await stack.stored_turns()
    assert [r["turn_id"] for r in rows] == [response.turn_id]
    assert await stack.hot_ids() == [response.turn_id]


async def test_hydrate_after_restart(stack):
    """a new bot instance with empty working memory continues with the newest budget window."""
    bot_a = await stack.make_bot(max_context_turns=2)
    for text in ("q1", "q2", "q3"):
        await _ask(bot_a, text)
    await _eventually(lambda: stack.has_turns(3))
    client_b = RecordingClient()
    bot_b = await stack.make_bot(memory=InMemoryConversation(), max_context_turns=2, client=client_b)
    await _ask(bot_b, "again")
    texts = [m.content for m in client_b.calls[-1]["history"] if m.role == "user"]
    assert texts == ["q2", "q3"]  # the newest two, ascending — not the oldest
    history = await bot_b.conversation_memory.get_history(USER, SESSION, chatbot_id=KEY)
    assert [t.user_message for t in history.turns] == ["q2", "q3", "again"]


async def test_hydration_race_two_workers(stack):
    """two concurrent first requests, one installed history."""
    seeder = await stack.make_bot()
    await _ask(seeder, "old1")
    await _ask(seeder, "old2")
    await _eventually(lambda: stack.has_turns(2))

    class _Spy(InMemoryConversation):
        installs: List[bool] = []

        async def install_history(self, *a, **kw):
            result = await super().install_history(*a, **kw)
            self.installs.append(result)
            return result

    mem = _Spy()
    mem.installs = []
    worker_1 = await stack.make_bot(memory=mem)
    worker_2 = await stack.make_bot(memory=mem)
    await asyncio.gather(_ask(worker_1, "new1"), _ask(worker_2, "new2"))
    assert mem.installs.count(True) == 1
    history = await mem.get_history(USER, SESSION, chatbot_id=KEY)
    messages = [t.user_message for t in history.turns]
    assert messages[:2] == ["old1", "old2"] and sorted(messages[2:]) == ["new1", "new2"]
    assert len({t.turn_id for t in history.turns}) == 4


async def test_delete_during_delayed_write(tmp_path):
    """pause the subscriber, delete the session, resume, replay the DLQ: nothing becomes visible or hydrates."""
    gate = asyncio.Event()
    stack = await _build(tmp_path, gate)
    try:
        bot = await stack.make_bot()
        await _ask(bot)

        async def captured():
            return bool(stack.envelopes)

        await _eventually(captured)  # published, the subscriber is held at the gate
        await stack.storage.delete_conversation(USER, SESSION, agent_id=AGENT)
        gate.set()
        await _eventually(lambda: _flag(stack.handler_done))
        assert await stack.stored_turns() == []
        with pytest.raises(ConversationDeletedError):  # reads refuse a tombstoned conversation
            await stack.storage.load_conversation(USER, SESSION, agent_id=AGENT)
        assert await stack.hot_ids() == []
        with pytest.raises(SessionDeletedError):
            await ChatStorageHydrationSource(stack.backend).load_turns(AGENT, USER, SESSION, 5)
        await stack.storage.handle_turn_completed(stack.envelopes[0])  # replay: terminal ack, still nothing
        assert await stack.stored_turns() == [] and await stack.hot_ids() == []
    finally:
        gate.set()
        await shutdown_turn_persistence(stack.handle)
        await stack.storage.close()


async def _flag(event: asyncio.Event) -> bool:
    return event.is_set()


async def test_delete_during_hydration_install(stack):
    """the post-install guard recheck rejects the session."""
    seeder = await stack.make_bot()
    await _ask(seeder, "a")
    await _ask(seeder, "b")
    await _eventually(lambda: stack.has_turns(2))

    class _FlippingSource(ChatStorageHydrationSource):
        def __init__(self, backend):
            super().__init__(backend)
            self.checks = 0

        async def is_deleted(self, agent_name, user_id, session_id):
            self.checks += 1
            return self.checks > 1  # the delete lands after the first (pre-load) check

    bot_b = await stack.make_bot(memory=InMemoryConversation(), source=_FlippingSource(stack.backend))
    with pytest.raises(SessionDeletedError):
        await _ask(bot_b, "again")
    assert await bot_b.conversation_memory.get_history(USER, SESSION, chatbot_id=KEY) is None


async def test_deleted_turn_stays_deleted(stack):
    """a delayed upsert cannot undo a turn deletion."""
    bot = await stack.make_bot()
    first = await _ask(bot, "one")
    second = await _ask(bot, "two")
    await _eventually(lambda: stack.has_turns(2))
    assert await stack.storage.delete_turn(SESSION, first.turn_id, user_id=USER, agent_id=AGENT) is True
    envelope = next(e for e in stack.envelopes if e.payload["turn"]["turn_id"] == first.turn_id)
    await stack.storage.handle_turn_completed(envelope)  # terminal ack, no exception
    assert [r["turn_id"] for r in await stack.stored_turns()] == [second.turn_id]
    assert await stack.hot_ids() == [second.turn_id]


async def test_guard_unavailable_fails_closed(stack):
    """no stale history is served and no session is initialized."""

    class _GuardDown(ChatStorageHydrationSource):
        async def is_deleted(self, agent_name, user_id, session_id):
            raise HydrationUnavailableError("redis down")

    class _GuardBroken(ChatStorageHydrationSource):
        async def is_deleted(self, agent_name, user_id, session_id):
            raise RuntimeError("unexpected failure")  # an unknown guard failure must also fail closed

    client = RecordingClient()
    bot = await stack.make_bot(client=client, source=_GuardDown(stack.backend))
    await bot.conversation_memory.create_history(USER, SESSION, chatbot_id=KEY)  # a history that must not be served
    with pytest.raises(HydrationUnavailableError):
        await _ask(bot)
    with pytest.raises(HydrationUnavailableError):
        await _ask(bot, session="unseen")
    assert client.calls == []  # the LLM was never reached
    broken = await stack.make_bot(client=client, source=_GuardBroken(stack.backend))
    with pytest.raises(HydrationUnavailableError):
        await _ask(broken)
    assert client.calls == []
    assert await bot.conversation_memory.get_history(USER, "unseen", chatbot_id=KEY) is None


async def test_stream_disconnect_stores_partial_turn(stack):
    """a mid-stream disconnect stores a partial turn with error state (spec §4, §7)."""
    # (1) caller disconnect: consume one chunk, then close the generator
    bot = await stack.make_bot(client=RecordingClient(hang_after=1))
    stream = bot.ask_stream("q", user_id=USER, session_id=SESSION, use_vector_context=False)
    assert await stream.__anext__() == "par"
    await stream.aclose()
    await _eventually(lambda: stack.has_turns(1))
    row = (await stack.stored_turns())[0]
    assert row["assistant_response"] == "par" and row["error"]
    # the next ask on the same session proceeds cleanly
    follow = await stack.make_bot()
    await _ask(follow, "next")
    await _eventually(lambda: stack.has_turns(2))
    # (2) LLM stream failure
    failing = await stack.make_bot(client=RecordingClient(fail_after=1))
    async for _ in failing.ask_stream("q2", user_id=USER, session_id="s2", use_vector_context=False):
        pass
    await _eventually(lambda: stack.has_turns(1, session="s2"))
    row2 = (await stack.stored_turns(session="s2"))[0]
    assert row2["assistant_response"] == "par" and "boom" in row2["error"]
