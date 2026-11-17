"""Regression coverage for token counts on raw turn-event snapshots."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from parrot.bots.abstract import AbstractBot
from parrot.memory import ConversationTurn, InMemoryConversation
from parrot.memory.compaction.tokens import HeuristicCounter


class _Bot(AbstractBot):
    """Minimal concrete bot for exercising the conversation-turn writer."""

    async def ask(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - not used
        raise NotImplementedError

    async def ask_stream(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - not used
        raise NotImplementedError

    async def conversation(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - not used
        raise NotImplementedError

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - not used
        raise NotImplementedError


class _RecordingPublisher:
    """Capture completed-turn events handed to the outbox boundary."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, event: Any) -> None:
        """Record one completed-turn event."""
        self.events.append(event)


class _RecordingCounter(HeuristicCounter):
    """Deterministic token counter that can fail its first call."""

    def __init__(self, *, fail_first: bool = False) -> None:
        self.calls = 0
        self.fail_first = fail_first

    def count(self, text: str) -> int:
        """Count text, optionally raising on the first invocation."""
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("counter unavailable")
        return super().count(text)


class _TrackingMemory(InMemoryConversation):
    """Record how many counter calls happened before ``add_turn`` began."""

    def __init__(self, counter: _RecordingCounter) -> None:
        super().__init__(token_counter=counter)
        self.counter = counter
        self.count_calls_at_add: int | None = None

    async def add_turn(self, *args: Any, **kwargs: Any) -> None:
        """Capture the counter state before delegating to normal persistence."""
        self.count_calls_at_add = self.counter.calls
        await super().add_turn(*args, **kwargs)


def _bot(counter: _RecordingCounter, *, publish: bool) -> tuple[_Bot, _TrackingMemory, _RecordingPublisher | None]:
    """Build a bot with deterministic memory and an optional publisher."""
    bot = _Bot(name="snapshot-bot", chatbot_id="bot-id", injection_detection=False)
    memory = _TrackingMemory(counter)
    publisher = _RecordingPublisher() if publish else None
    bot.conversation_memory = memory
    bot.turn_publisher = publisher
    return bot, memory, publisher


def _turn(turn_id: str = "turn-1") -> ConversationTurn:
    """Build one raw attributed turn."""
    return ConversationTurn(
        turn_id=turn_id,
        user_id="user-1",
        user_message="hello from the user",
        assistant_response="hello from the assistant",
        chatbot_id="bot-id",
    )


async def test_published_snapshot_carries_raw_token_count() -> None:
    """AC-1: a published raw snapshot contains the complete token-count shape."""
    bot, _, publisher = _bot(_RecordingCounter(), publish=True)
    turn = _turn()

    await bot.save_conversation_turn("user-1", "session-1", turn)

    assert publisher is not None
    token_count = publisher.events[0].turn["token_count"]
    assert set(token_count) == {"user", "assistant", "tools", "total", "tokenizer"}
    assert token_count["total"] > 0
    assert turn.token_count is None


async def test_publisher_does_not_change_working_memory_token_count() -> None:
    """AC-2: attaching a publisher does not alter the working-memory count."""
    published_bot, published_memory, _ = _bot(_RecordingCounter(), publish=True)
    local_bot, local_memory, _ = _bot(_RecordingCounter(), publish=False)
    await published_memory.create_history("user-1", "session-1", chatbot_id="bot-id")
    await local_memory.create_history("user-1", "session-1", chatbot_id="bot-id")

    await published_bot.save_conversation_turn("user-1", "session-1", _turn("published"))
    await local_bot.save_conversation_turn("user-1", "session-1", _turn("local"))

    published_history = await published_memory.get_history("user-1", "session-1", chatbot_id="bot-id")
    local_history = await local_memory.get_history("user-1", "session-1", chatbot_id="bot-id")
    assert published_history is not None
    assert local_history is not None
    assert published_history.turns[0].token_count == local_history.turns[0].token_count


async def test_no_publisher_does_not_count_before_add_turn() -> None:
    """AC-3: without a publisher, token counting starts inside ``add_turn``."""
    counter = _RecordingCounter()
    bot, memory, publisher = _bot(counter, publish=False)

    snapshot = await bot.save_conversation_turn("user-1", "session-1", _turn())

    assert snapshot is None
    assert publisher is None
    assert memory.count_calls_at_add == 0
    assert counter.calls > 0


async def test_snapshot_count_failure_warns_but_still_publishes_and_saves(caplog: pytest.LogCaptureFixture) -> None:
    """AC-4: a snapshot-count failure leaves the count null without losing the turn."""
    bot, memory, publisher = _bot(_RecordingCounter(fail_first=True), publish=True)
    await memory.create_history("user-1", "session-1", chatbot_id="bot-id")

    with caplog.at_level(logging.WARNING, logger=bot.logger.name):
        await bot.save_conversation_turn("user-1", "session-1", _turn("turn-failure"))

    assert publisher is not None
    assert publisher.events[0].turn["token_count"] is None
    history = await memory.get_history("user-1", "session-1", chatbot_id="bot-id")
    assert history is not None
    assert history.turns[0].turn_id == "turn-failure"
    assert history.turns[0].token_count is not None
    assert "turn-failure" in caplog.text
