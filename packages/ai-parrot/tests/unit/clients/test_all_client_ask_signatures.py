"""Cross-client signature guard (FEAT-524, TASK-2815).

Spec §4 M5 row ``test_all_client_ask_signatures`` and §5's acceptance criterion
that ``user_id``/``session_id`` appear in no ``ask``/``ask_stream`` signature.

This is the feature's structural backstop: it discovers every concrete
``AbstractClient`` subclass by import rather than from a hand-maintained list,
so a client added (or, per spec §7, *relocated* by FEAT-523) after this lands
still gets checked.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import textwrap
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
    "parrot.clients.openai.codex_agent",
    "parrot.clients.gemma4",
    "parrot.clients.google.client",
    "parrot.clients.openai.client",
    "parrot.clients.grok",
    "parrot.clients.groq",
    "parrot.clients.hf",
    "parrot.clients.google.live",
    "parrot.clients.local.client",
    "parrot.clients.moonshot.client",
    "parrot.clients.nvidia.client",
    "parrot.clients.openai_base",
    "parrot.clients.openrouter.client",
    "parrot.clients.vllm.client",
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

    has_var_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    assert (
        "history" in parameters or has_var_kwargs
    ), f"{client_id}.{method} can neither take history= nor absorb it via **kwargs"


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

    assert "conversation_memory" not in parameters, f"{client_id}.__init__ still accepts conversation_memory"


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
@pytest.mark.parametrize("method", ["ask", "ask_stream"])
def test_declared_history_is_actually_consumed(client_id: str, method: str):
    """A client that DECLARES ``history`` must actually read it.

    Regression guard for a real bug: ``gemma4`` and ``hf`` implement
    ``ask_stream`` by delegating to their own ``ask()`` and chunking the
    result. Both declared ``history`` in the signature — so
    ``test_all_client_ask_signatures`` passed — but forwarded
    ``user_id=``/``session_id=`` instead of ``history=``, silently dropping the
    whole conversation on every streamed round. Checking the signature is not
    enough; the parameter has to be *used*.

    A client that deliberately ignores history (``claude_agent``, ``live`` —
    both own a provider-side session) must say so explicitly with ``del
    history``, which counts as consuming it.
    """
    function = inspect.unwrap(getattr(CLIENTS[client_id], method))
    try:
        source = textwrap.dedent(inspect.getsource(function))
    except (OSError, TypeError):  # pragma: no cover - C or generated code
        pytest.skip(f"no source available for {client_id}.{method}")

    tree = ast.parse(source)
    node = next(
        n for n in ast.walk(tree) if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == method
    )
    params = {a.arg for a in node.args.args + node.args.kwonlyargs}
    if "history" not in params:
        pytest.skip(f"{client_id}.{method} takes history via **kwargs")

    uses = [
        n
        for n in ast.walk(node)
        if isinstance(n, ast.Name) and n.id == "history" and isinstance(n.ctx, (ast.Load, ast.Del))
    ]
    assert uses, (
        f"{client_id}.{method} declares `history` but never reads or `del`s it — "
        "the rendered conversation is being silently dropped"
    )


@pytest.mark.parametrize("client_id", CLIENT_IDS)
@pytest.mark.parametrize("method", ["ask", "ask_stream"])
def test_no_client_forwards_removed_ids_to_itself(client_id: str, method: str):
    """No client passes ``user_id=``/``session_id=`` into another ask() call.

    Those kwargs no longer exist on any ``ask``/``ask_stream``, so a surviving
    ``self.ask(..., user_id=...)`` either lands in ``**kwargs`` and reaches the
    provider SDK as an unknown argument, or masks a dropped ``history=``.
    """
    function = inspect.unwrap(getattr(CLIENTS[client_id], method))
    try:
        source = textwrap.dedent(inspect.getsource(function))
    except (OSError, TypeError):  # pragma: no cover
        pytest.skip(f"no source available for {client_id}.{method}")

    tree = ast.parse(source)
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        func = call.func
        # Only self.ask(...) / self.ask_stream(...) style delegations.
        if not (isinstance(func, ast.Attribute) and func.attr in ("ask", "ask_stream")):
            continue
        forwarded = {kw.arg for kw in call.keywords if kw.arg}
        offenders = forwarded & {"user_id", "session_id"}
        assert not offenders, (
            f"{client_id}.{method} forwards {sorted(offenders)} into "
            f"self.{func.attr}(), which no longer accepts them"
        )


@pytest.mark.parametrize("client_id", CLIENT_IDS)
def test_every_client_can_format_history(client_id: str):
    """``_format_history`` is inherited or overridden, never missing."""
    assert callable(getattr(CLIENTS[client_id], "_format_history", None)), client_id
    assert callable(getattr(CLIENTS[client_id], "_build_messages", None)), client_id
