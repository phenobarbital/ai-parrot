"""FEAT-886 M1 — ChatStorage.delete_turn clears the hot tier; hot TTL comes from CHAT_HOT_TTL_HOURS."""
from __future__ import annotations

import logging

import parrot.memory as parrot_memory
import parrot.storage.chat as chat_module
from parrot.memory import ConversationTurn, InMemoryConversation
from parrot.storage.chat import ChatStorage


class _ColdBackend:
    """Duck-typed cold tier recording deletes (ChatStorage only calls these two methods here)."""

    def __init__(self) -> None:
        self.deleted: list[tuple[str, str, str, str]] = []

    async def delete_turn(self, user_id, agent_id, session_id, turn_id) -> bool:
        self.deleted.append((user_id, agent_id, session_id, turn_id))
        return True

    async def update_thread(self, **kwargs) -> None:
        return None


async def _seed(hot: InMemoryConversation) -> None:
    await hot.create_history("u", "s", chatbot_id="agent-1")
    for tid in ("t1", "t2"):
        await hot.add_turn(
            "u", "s",
            ConversationTurn(turn_id=tid, user_id="u", user_message="q", assistant_response="a", chatbot_id="agent-1"),
            chatbot_id="agent-1",
        )


async def test_delete_turn_clears_hot_tier():
    """The turn is gone from the hot tier AND the cold tier."""
    hot = InMemoryConversation()
    await _seed(hot)
    cold = _ColdBackend()
    storage = ChatStorage(redis_conversation=hot, dynamodb=cold)
    assert await storage.delete_turn("s", "t1", user_id="u", agent_id="agent-1") is True
    history = await hot.get_history("u", "s", chatbot_id="agent-1")
    assert [t.turn_id for t in history.turns] == ["t2"]
    assert cold.deleted == [("u", "agent-1", "s", "t1")]


async def test_delete_turn_hot_failure_is_logged_not_raised(caplog):
    """A failing hot tier does not change the return value and does not raise."""

    class _Broken(InMemoryConversation):
        async def update_history(self, history) -> None:
            raise RuntimeError("redis down")

    hot = _Broken()
    await _seed(hot)
    storage = ChatStorage(redis_conversation=hot, dynamodb=_ColdBackend())
    with caplog.at_level(logging.WARNING):
        assert await storage.delete_turn("s", "t1", user_id="u", agent_id="agent-1") is True
    assert any("t1" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


async def test_initialize_passes_history_ttl(monkeypatch):
    """CHAT_HOT_TTL_HOURS drives RedisConversation(history_ttl=...); 0 disables it."""
    seen: list = []

    class _Recorder:
        def __init__(self, **kwargs) -> None:
            seen.append(kwargs.get("history_ttl", "missing"))

    monkeypatch.setattr(parrot_memory, "RedisConversation", _Recorder)
    for hours, expected in ((2, 7200), (0, None)):
        monkeypatch.setattr(chat_module, "CHAT_HOT_TTL_HOURS", hours)
        storage = ChatStorage(dynamodb=_ColdBackend())
        await storage.initialize()
    assert seen == [7200, None]
