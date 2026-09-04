"""Cross-client signature guard (FEAT-524, TASK-2815).

Spec §4 M5 row ``test_all_client_ask_signatures`` and §5's acceptance criterion
that ``user_id``/``session_id`` appear in no ``ask``/``ask_stream`` signature.

This is the feature's structural backstop: it discovers every concrete
``AbstractClient`` subclass by import rather than from a hand-maintained list,
so a client added (or, per spec §7, *relocated* by FEAT-523) after this lands
still gets checked.
"""

from __future__ import annotations

import importlib
import inspect
from typing import Any, Dict

import pytest

from parrot.clients.base import AbstractClient

#: Every module under ``parrot.clients`` that defines a concrete client.
#: Modules whose optional SDK is missing are skipped, not failed.
CLIENT_MODULES = [
    "parrot.clients.anthropic_backends",
    "parrot.clients.bedrock",
    "parrot.clients.claude",
    "parrot.clients.claude_agent",
    "parrot.clients.codex_agent",
    "parrot.clients.gemma4",
    "parrot.clients.google.client",
    "parrot.clients.gpt",
    "parrot.clients.grok",
    "parrot.clients.groq",
    "parrot.clients.hf",
    "parrot.clients.live",
    "parrot.clients.localllm",
    "parrot.clients.moonshot",
    "parrot.clients.nvidia",
    "parrot.clients.openai_base",
    "parrot.clients.openrouter",
    "parrot.clients.vllm",
    "parrot.clients.zai",
]


def _discover() -> Dict[str, Any]:
    """Import every client module and collect its concrete client classes."""
    found: Dict[str, Any] = {}
    for module_name in CLIENT_MODULES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:  # optional provider SDK absent in this environment
            continue
        for obj in vars(module).values():
            if (
                inspect.isclass(obj)
                and issubclass(obj, AbstractClient)
                and obj is not AbstractClient
                and obj.__module__ == module.__name__
                and not inspect.isabstract(obj)
            ):
                found[f"{obj.__module__}.{obj.__qualname__}"] = obj
    return found


CLIENTS = _discover()
CLIENT_IDS = sorted(CLIENTS)


def test_discovery_found_every_client():
    """Guard the guard: a broken import must not silently empty the matrix."""
    assert len(CLIENTS) >= 15, sorted(CLIENTS)
    # A few that must always be present in this environment.
    names = {name.rsplit(".", 1)[-1] for name in CLIENTS}
    assert {"AnthropicClient", "OpenAIClient", "GoogleGenAIClient", "GrokClient"} <= names


@pytest.mark.parametrize("client_id", CLIENT_IDS)
@pytest.mark.parametrize("method", ["ask", "ask_stream"])
def test_all_client_ask_signatures(client_id: str, method: str):
    """No client's ``ask``/``ask_stream`` takes ``user_id`` or ``session_id``."""
    parameters = inspect.signature(getattr(CLIENTS[client_id], method)).parameters

    assert "user_id" not in parameters, f"{client_id}.{method} still takes user_id"
    assert "session_id" not in parameters, f"{client_id}.{method} still takes session_id"


@pytest.mark.parametrize("client_id", CLIENT_IDS)
@pytest.mark.parametrize("method", ["ask", "ask_stream"])
def test_all_clients_accept_history(client_id: str, method: str):
    """Every client accepts ``history`` — explicitly, or via ``**kwargs``."""
    parameters = inspect.signature(getattr(CLIENTS[client_id], method)).parameters

    has_var_kwargs = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()
    )
    assert "history" in parameters or has_var_kwargs, (
        f"{client_id}.{method} can neither take history= nor absorb it via **kwargs"
    )


@pytest.mark.parametrize("client_id", CLIENT_IDS)
@pytest.mark.parametrize("method", ["ask", "ask_stream"])
def test_no_client_takes_stateless(client_id: str, method: str):
    """``stateless`` died with the helper it belonged to (spec §5).

    Statelessness is now expressed by simply not passing ``history``.
    """
    parameters = inspect.signature(getattr(CLIENTS[client_id], method)).parameters

    assert "stateless" not in parameters, f"{client_id}.{method} still takes stateless"


@pytest.mark.parametrize("client_id", CLIENT_IDS)
def test_no_client_constructor_takes_conversation_memory(client_id: str):
    """Clients are memory-less: no ``__init__`` accepts a conversation store."""
    parameters = inspect.signature(CLIENTS[client_id].__init__).parameters

    assert "conversation_memory" not in parameters, (
        f"{client_id}.__init__ still accepts conversation_memory"
    )


@pytest.mark.parametrize("client_id", CLIENT_IDS)
def test_no_client_instance_exposes_memory_api(client_id: str):
    """The removed conversation-memory surface is gone from every subclass."""
    client = CLIENTS[client_id]

    for attribute in (
        "_prepare_conversation_context",
        "_update_conversation_memory",
        "_get_chatbot_key",
        "start_conversation",
        "get_conversation",
        "clear_conversation",
        "delete_conversation",
    ):
        assert not hasattr(client, attribute), f"{client_id} still has {attribute}"


@pytest.mark.parametrize("client_id", CLIENT_IDS)
def test_every_client_can_format_history(client_id: str):
    """``_format_history`` is inherited or overridden, never missing."""
    assert callable(getattr(CLIENTS[client_id], "_format_history", None)), client_id
    assert callable(getattr(CLIENTS[client_id], "_build_messages", None)), client_id
