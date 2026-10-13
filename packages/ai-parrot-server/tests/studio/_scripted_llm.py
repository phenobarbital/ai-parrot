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


KEYED_PROVIDER = "scripted-keyed"
SERVER_KEY_ENV = "SCRIPTED_KEYED_API_KEY"


class KeyEchoClient(ScriptedClient):
    """Replies ``key:<api_key it was built with>`` so a test can read WHICH key served the call (PA-2).

    Declares a server key variable like a shipped satellite does; a client built without ``api_key=`` is the
    server-key path (``key:None``).
    """

    client_type = KEYED_PROVIDER
    client_name = KEYED_PROVIDER
    credential_env = (SERVER_KEY_ENV,)

    async def ask(self, prompt, model=None, *args, history=None, **kwargs):
        text = f"key:{self.api_key}"
        return AIMessage(
            input=prompt, output=text, response=text, model=model or "m", provider=KEYED_PROVIDER,
            usage=CompletionUsage(),
        )
