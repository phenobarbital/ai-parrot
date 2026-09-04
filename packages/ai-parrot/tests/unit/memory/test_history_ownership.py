"""FEAT-524 regression tests — conversation history has exactly one owner.

Spec: ``sdd/specs/conversation-history-ownership.spec.md`` §3 Module 1, §4 M1.

These tests pin the three symptoms of the double-ownership bug documented in
spec §1.  They are committed **red** against the pre-FEAT-524 code and turn
green once TASK-2816 lands:

1. ``test_bot_round_persists_exactly_one_turn`` — today both
   :meth:`AbstractClient._update_conversation_memory` and ``BaseBot.ask``
   write a :class:`~parrot.memory.ConversationTurn` for the same round, so
   two rounds leave **four** turns in the history.
2. ``test_history_reaches_provider_once`` — today round 1's text reaches the
   provider twice on round 2: once as replayed provider messages (from the
   client) and once as the ``## Conversation Context:`` digest the bot
   injects into the system prompt.
3. ``test_system_prompt_has_no_history_digest`` — that digest must not exist
   at all after FEAT-524.

The :class:`RecordingClient` stub is written to work **both** before and
after the change: it probes for the pre-FEAT-524 helpers
(``_prepare_conversation_context`` / ``_update_conversation_memory``) with
:func:`getattr` and falls back to the post-FEAT-524 ``_build_messages`` /
``history=`` path when they are gone.  That way the same file measures the
same three properties across the cut instead of being rewritten mid-feature.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

import pytest

from parrot.bots.base import BaseBot
from parrot.clients.base import AbstractClient
from parrot.memory import InMemoryConversation
from parrot.models import AIMessage
from parrot.models.responses import CompletionUsage


class RecordingClient(AbstractClient):
    """Offline stub client that records what it was asked to send.

    Records one entry per :meth:`ask` call holding the prompt, the effective
    system prompt and the provider messages it would have transmitted.  It
    never performs network I/O and returns a canned
    :class:`~parrot.models.responses.AIMessage`.
    """

    client_type = "recording"
    supported_models = ["stub"]

    def __init__(self, reply: str = "ok", **kwargs: Any) -> None:
        kwargs.setdefault("model", "stub")
        super().__init__(**kwargs)
        self.calls: List[Dict[str, Any]] = []
        self.reply = reply

    async def get_client(self) -> "RecordingClient":
        """Return self — there is no provider SDK behind this stub."""
        return self

    async def _ensure_client(self) -> "RecordingClient":
        """No-op: bypass the per-loop SDK client bootstrap."""
        return self

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> AIMessage:
        """Record the outgoing payload and return the canned reply."""
        system_prompt = kwargs.get("system_prompt")
        user_id = kwargs.get("user_id")
        session_id = kwargs.get("session_id")

        # Pre-FEAT-524: the base class loads the history itself and replays it.
        prepare = getattr(self, "_prepare_conversation_context", None)
        history_obj = None
        if prepare is not None and user_id and session_id:
            messages, history_obj, system_prompt = await prepare(
                prompt, None, user_id, session_id, system_prompt
            )
        else:
            # Post-FEAT-524: the bot hands us an already rendered history.
            build_messages = getattr(self, "_build_messages", None)
            if build_messages is not None:
                messages = build_messages(prompt, None, kwargs.get("history"))
            else:
                messages = self._prepare_messages(prompt)[0]

        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "messages": messages,
                "history": list(kwargs.get("history") or ()),
            }
        )

        response = AIMessage(
            input=prompt,
            output=self.reply,
            model="stub",
            provider="stub",
            usage=CompletionUsage(),
            turn_id=str(uuid.uuid4()),
        )

        # Pre-FEAT-524: the client also writes its own turn — the second
        # writer this feature removes.
        update_memory = getattr(self, "_update_conversation_memory", None)
        if update_memory is not None and user_id and session_id:
            await update_memory(
                user_id,
                session_id,
                history_obj,
                messages,
                system_prompt,
                response.turn_id,
                prompt,
                self.reply,
            )
        return response

    async def ask_stream(self, prompt: str, **kwargs: Any):
        """Yield the canned reply as a single chunk."""
        yield self.reply

    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]):
        """Not exercised by these tests."""
        raise NotImplementedError

    async def invoke(self, prompt: str, **kwargs: Any):
        """Not exercised by these tests."""
        raise NotImplementedError


@pytest.fixture
async def bot() -> BaseBot:
    """A configured ``BaseBot`` wired to a ``RecordingClient`` + in-memory store.

    ``configure()`` is what injects the bot's conversation memory into the
    client today (``AbstractBot._create_llm_client``), so it must run for the
    double-write to be observable at all.
    """
    client = RecordingClient()
    instance = BaseBot(
        name="history-ownership-probe",
        llm=client,
        memory_type="memory",
        injection_detection=False,
    )
    await instance.configure()
    assert isinstance(instance.conversation_memory, InMemoryConversation)
    return instance


#: Deliberately unlikely to occur in any static prompt boilerplate — the
#: original "first"/"second" wording collided with the tool-usage instructions
#: ("Call the first operation"), which made occurrence-counting meaningless.
ROUND_1_TEXT = "zorblatt-round-one"
ROUND_2_TEXT = "zorblatt-round-two"


async def _two_rounds(instance: BaseBot) -> None:
    """Run two stateful rounds against the same (user, session) pair."""
    await instance.ask(ROUND_1_TEXT, user_id="u", session_id="s", use_vector_context=False)
    await instance.ask(ROUND_2_TEXT, user_id="u", session_id="s", use_vector_context=False)


@pytest.mark.asyncio
async def test_bot_round_persists_exactly_one_turn(bot: BaseBot) -> None:
    """Two rounds ⇒ exactly two persisted turns (one writer, not two)."""
    await _two_rounds(bot)

    memory = bot.conversation_memory
    history = await memory.get_history(
        "u", "s", chatbot_id=getattr(bot, "memory_key_id", None)
    )
    assert history is not None, "history was never created"
    assert len(history.turns) == 2, (
        f"expected 1 turn per round, got {len(history.turns)} turns for 2 rounds "
        "— the client and the bot are both writing"
    )


@pytest.mark.asyncio
async def test_history_reaches_provider_once(bot: BaseBot) -> None:
    """Round 1's text must appear exactly once in round 2's outgoing payload.

    Counted over only what is actually transmitted — the prompt, the system
    prompt and the provider messages. The stub also records the raw ``history``
    argument it was handed, but that is the *input* to the formatting step, not
    a second copy on the wire, so including it would double-count by construction.
    """
    await _two_rounds(bot)

    call = bot.get_client().calls[-1]
    payload = json.dumps(
        {k: call[k] for k in ("prompt", "system_prompt", "messages")}, default=str
    )

    assert payload.count(ROUND_1_TEXT) == 1, (
        "round-1 text reached the provider more than once on round 2 — "
        "history is injected both as replayed messages and as a system-prompt digest"
    )


@pytest.mark.asyncio
async def test_history_reaches_provider_as_messages(bot: BaseBot) -> None:
    """Round 1 is replayed as alternating messages, not as system-prompt prose."""
    await _two_rounds(bot)

    call = bot.get_client().calls[-1]

    assert [m["role"] for m in call["messages"]] == ["user", "assistant", "user"]
    assert call["messages"][0]["content"][0]["text"] == ROUND_1_TEXT
    assert call["messages"][-1]["content"][0]["text"] == ROUND_2_TEXT
    assert ROUND_1_TEXT not in (call["system_prompt"] or "")


@pytest.mark.asyncio
async def test_system_prompt_has_no_history_digest(bot: BaseBot) -> None:
    """The bot must not condense history into the system prompt."""
    await _two_rounds(bot)

    client = bot.get_client()
    system_prompt = client.calls[-1]["system_prompt"] or ""
    assert "## Conversation Context" not in system_prompt, (
        "the system prompt still carries the conversation digest "
        "(AbstractBot.build_conversation_context)"
    )
