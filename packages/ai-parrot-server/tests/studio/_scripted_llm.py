"""A test-owned LLM client: the only fake in the Studio conversation-memory tests (everything else is real)."""

from __future__ import annotations

from parrot.clients.base import AbstractClient
from parrot.models import AIMessage, CompletionUsage

PROVIDER = "scripted"


class ScriptedClient(AbstractClient):
    """Replies ``scripted:<history messages received>:<prompt>`` so a test can read the history the bot handed over."""

    client_type = PROVIDER
    client_name = PROVIDER
    default_model = "m"

    async def get_client(self, **_hints):
        return object()

    async def ask(self, prompt, model=None, *args, history=None, **kwargs):
        text = f"scripted:{len(history or [])}:{prompt}"
        return AIMessage(
            input=prompt, output=text, response=text, model=model or "m", provider=PROVIDER, usage=CompletionUsage()
        )

    async def ask_stream(self, *args, **kwargs):  # pragma: no cover - not used
        raise NotImplementedError

    async def resume(self, *args, **kwargs):  # pragma: no cover - not used
        raise NotImplementedError

    async def invoke(self, *args, **kwargs):  # pragma: no cover - not used
        raise NotImplementedError


def history_seen(response_text: str) -> int:
    """The number of history messages the scripted client received, from its reply."""
    return int(response_text.split(":")[1])
