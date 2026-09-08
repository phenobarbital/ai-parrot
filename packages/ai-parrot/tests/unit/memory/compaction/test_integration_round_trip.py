"""Integration tests for FEAT-525 per-turn conversation compaction (no network, stub clients)."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import pytest

from parrot.bots.base import BaseBot
from parrot.clients.base import AbstractClient
from parrot.memory import ContextBudget, InMemoryConversation
from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import ToolInvocation
from parrot.memory.compaction.recover import bind_read_omitted_content
from parrot.memory.compaction.tokens import HeuristicCounter
from parrot.models import AIMessage
from parrot.models.basic import ToolCall
from parrot.models.responses import CompletionUsage
from parrot.observability.context import invocation_context


class _RecordingClient(AbstractClient):
    """Offline stub client recording ``history=`` per call; no tool activity."""

    client_type = "stub"
    supported_models = ["stub"]

    def __init__(self, reply: str = "ok", **kwargs: Any) -> None:
        kwargs.setdefault("model", "stub")
        super().__init__(**kwargs)
        self.reply = reply
        self.calls: List[Dict[str, Any]] = []

    async def get_client(self) -> "_RecordingClient":
        return self

    async def _ensure_client(self) -> "_RecordingClient":
        return self

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> AIMessage:
        self.calls.append({"prompt": prompt, "history": list(kwargs.get("history") or ())})
        return AIMessage(
            input=prompt,
            output=self.reply,
            model="stub",
            provider="stub",
            usage=CompletionUsage(input_tokens=50, output_tokens=10),
            # Deterministic (not uuid4): two independently-instantiated
            # clients driving the same round sequence must produce the
            # SAME turn_id per round for a byte-equality comparison across
            # them to mean anything.
            turn_id=f"turn-{len(self.calls)}",
        )

    async def ask_stream(self, prompt: str, **kwargs: Any):
        yield self.reply

    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]):
        raise NotImplementedError

    async def invoke(self, prompt: str, **kwargs: Any):
        raise NotImplementedError


class _DatasetClient(_RecordingClient):
    """Stub client whose every reply carries one large ("dataset") tool result."""

    def __init__(self, dataset: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.dataset = dataset

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> AIMessage:
        self.calls.append({"prompt": prompt, "history": list(kwargs.get("history") or ())})
        tool_call = ToolCall(
            id=str(uuid.uuid4()),
            name="query_database",
            arguments={"sql": prompt},
            result=self.dataset,
            execution_time=0.5,
        )
        return AIMessage(
            input=prompt,
            output="query complete",
            model="stub",
            provider="stub",
            usage=CompletionUsage(input_tokens=200, output_tokens=20),
            tool_calls=[tool_call],
            turn_id=str(uuid.uuid4()),
        )


async def _make_bot(*, client, **bot_kwargs):
    mem = InMemoryConversation(token_counter=HeuristicCounter())
    bot = BaseBot(
        name=bot_kwargs.pop("name", "integration-probe"),
        llm=client,
        memory_type="memory",
        injection_detection=False,
        **bot_kwargs,
    )
    await bot.configure()
    bot.conversation_memory = mem
    bot._register_recovery_tool()
    return bot, client, mem


async def test_round_trip_database_agent_session():
    """12 rounds, each with an 8k-token tool result: pruning kicks in, recovery is lossless."""
    dataset = "d" * 32_000  # ~8_000 heuristic tokens — well above oversize_tool_tokens (2_000)
    client = _DatasetClient(dataset)
    bot, client, mem = await _make_bot(client=client, context_budget=ContextBudget(window=32_000))

    boundaries: List[int] = []
    for i in range(12):
        await bot.ask(f"query {i}", user_id="u", session_id="s", use_vector_context=False)
        history = await mem.get_history("u", "s", chatbot_id=bot.memory_key_id)
        comp = history.metadata.get("compaction", {})
        boundary_id = comp.get("boundary_turn_id")
        turn_ids = [t.turn_id for t in history.turns]
        boundaries.append(turn_ids.index(boundary_id) if boundary_id in turn_ids else -1)

        if i >= 3:
            rendered = client.calls[-1]["history"]
            omitted_count = sum("<tool-output-omitted" in m.content for m in rendered)
            assert omitted_count >= 1
            total = sum(HeuristicCounter().count(m.content) for m in rendered)
            assert total <= int(0.8 * bot.context_budget.available)

    # Boundary is monotonic: never points at an older turn than before.
    assert boundaries == sorted(boundaries)

    history = await mem.get_history("u", "s", chatbot_id=bot.memory_key_id)
    assert history.metadata["compaction"]["samples"] == 12

    # The very first round's tool output was offloaded and is recoverable
    # byte for byte through read_omitted_content.
    first_turn = history.turns[0]
    inv = first_turn.tool_invocations[0]
    assert "output" in inv.omitted

    fn = bind_read_omitted_content(mem)
    with invocation_context(bot.name, user_id="u", session_id="s", memory_key_id=bot.memory_key_id):
        recovered = await fn(content_id=inv.omitted["output"])
    assert recovered == dataset


async def test_round_trip_chat_session_unchanged():
    """40 text-only rounds render byte-identically with and without the budget."""
    disabled_bot, disabled_client, _ = await _make_bot(client=_RecordingClient(), context_budget=False)
    budgeted_bot, budgeted_client, _ = await _make_bot(client=_RecordingClient())

    for i in range(40):
        await disabled_bot.ask(f"hi {i}", user_id="u", session_id="s", use_vector_context=False)
        await budgeted_bot.ask(f"hi {i}", user_id="u", session_id="s", use_vector_context=False)
        assert disabled_client.calls[-1]["history"] == budgeted_client.calls[-1]["history"]


def _redis_available() -> bool:
    try:
        import redis as redis_sync

        from parrot.conf import REDIS_HISTORY_URL

        client = redis_sync.from_url(REDIS_HISTORY_URL, socket_connect_timeout=1)
        client.ping()
        client.close()
        return True
    except Exception:  # noqa: BLE001 — any connectivity failure means "skip"
        return False


@pytest.mark.skipif(not _redis_available(), reason="no Redis reachable")
async def test_redis_end_to_end():
    """One hset per turn; omission keys exist after a pruned write; cascade on delete_history."""
    from parrot.memory import RedisConversation

    prefix = "feat525-integration-test"
    mem = RedisConversation(key_prefix=prefix, token_counter=HeuristicCounter())
    user_id, session_id, chatbot_id = "u", "s", "bot"

    try:
        await mem.create_history(user_id, session_id, chatbot_id=chatbot_id)
        big_output = "d" * 32_000
        turn = ConversationTurn(
            turn_id="t0",
            user_id=user_id,
            user_message="q0",
            assistant_response="a0",
            chatbot_id=chatbot_id,
            tool_invocations=[ToolInvocation(tool_name="query_database", input={"sql": "q0"}, output=big_output)],
        )
        await mem.add_turn(user_id, session_id, turn, chatbot_id=chatbot_id)

        key = mem.omission_key(user_id, session_id, chatbot_id)
        content_key = f"{prefix}_omitted:{key}"
        turns_key = f"{prefix}_omitted_turns:{key}"
        assert await mem.redis.exists(content_key)
        assert await mem.redis.exists(turns_key)

        await mem.delete_history(user_id, session_id, chatbot_id=chatbot_id)
        assert not await mem.redis.exists(content_key)
        assert not await mem.redis.exists(turns_key)
    finally:
        await mem.close()
