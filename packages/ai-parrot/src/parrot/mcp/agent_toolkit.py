"""Serve a registered agent's own async methods as a local stdio MCP toolkit (FEAT-877).

Only the methods the author wrote on the agent's own class are exposed; every name a
framework class or mixin defines — and ``ask``/``ask_stream`` always — is reserved.
"""

from __future__ import annotations

import inspect
import logging
import types
from collections.abc import Awaitable, Callable
from typing import Any

from parrot.registry.registry import MCPLocalExposure

logger = logging.getLogger(__name__)

NEVER_EXPOSED: frozenset[str] = frozenset({"ask", "ask_stream"})


class AgentExposureError(ValueError):
    """An agent cannot be exposed as a local MCP toolkit; the message names the fix."""


def framework_agent_bases() -> tuple[type, ...]:
    """Return the generic agent bases, imported lazily.

    Returns:
        ``(AbstractBot, BaseBot, BasicBot, Chatbot, BasicAgent, Agent)``.
    """
    from parrot.bots.abstract import AbstractBot  # noqa: PLC0415
    from parrot.bots.agent import Agent, BasicAgent  # noqa: PLC0415
    from parrot.bots.base import BaseBot  # noqa: PLC0415
    from parrot.bots.basic import BasicBot  # noqa: PLC0415
    from parrot.bots.chatbot import Chatbot  # noqa: PLC0415

    return (AbstractBot, BaseBot, BasicBot, Chatbot, BasicAgent, Agent)


def _framework_classes(agent_cls: type) -> set[type]:
    """Classes whose public names are reserved for ``agent_cls`` (spec §2 step 1)."""
    bases = framework_agent_bases()
    abstract_bot = bases[0]
    framework: set[type] = set()
    for base in bases:
        framework.update(base.__mro__)
    framework.update(klass for klass in agent_cls.__mro__ if not issubclass(klass, abstract_bot))
    return framework


def own_coroutine_methods(agent_cls: type) -> dict[str, Callable[..., Awaitable[Any]]]:
    """Return the exposable candidates of ``agent_cls`` (spec §2 steps 1-4), ordered by name.

    Args:
        agent_cls: An ``AbstractBot`` subclass (never instantiated).

    Returns:
        Method name → the class function (unbound).
    """
    framework = _framework_classes(agent_cls)
    reserved: set[str] = set(NEVER_EXPOSED)
    for klass in framework:
        reserved.update(name for name in vars(klass) if not name.startswith("_"))
    candidates: dict[str, Callable[..., Awaitable[Any]]] = {}
    seen: set[str] = set()
    for klass in agent_cls.__mro__:
        if klass in framework:
            continue
        for name, value in vars(klass).items():
            if name in seen:
                continue
            seen.add(name)
            if (
                not name.startswith("_")
                and name not in reserved
                and isinstance(value, types.FunctionType)
                and inspect.iscoroutinefunction(value)
            ):
                candidates[name] = value
    return dict(sorted(candidates.items()))


def exposed_methods(
    agent_cls: type, exposure: MCPLocalExposure, *, agent_name: str | None = None
) -> dict[str, Callable[..., Awaitable[Any]]]:
    """Apply ``exposure.allow`` to the candidates (spec §2 step 5).

    Args:
        agent_cls: The agent class.
        exposure: The agent's ``mcp_local`` declaration.
        agent_name: Registry name used in error messages (defaults to the class name).

    Returns:
        Exposed method name → class function; allow order when ``allow`` is set, else by name.

    Raises:
        AgentExposureError: An allow entry is not a candidate, or the result is empty.
    """
    label = agent_name or agent_cls.__name__
    candidates = own_coroutine_methods(agent_cls)
    if exposure.allow is None:
        methods = candidates
    else:
        bad = list(dict.fromkeys(name for name in exposure.allow if name not in candidates))
        if bad:
            message = f"Agent '{label}': allow entries are not own-class public async methods: {', '.join(bad)}"
            if any(name in NEVER_EXPOSED for name in bad):
                message += " (ask/ask_stream are never exposed)"
            raise AgentExposureError(message)
        methods = {name: candidates[name] for name in dict.fromkeys(exposure.allow)}
    if not methods:
        raise AgentExposureError(f"Agent '{label}' ({agent_cls.__name__}) defines no exposable methods")
    return methods
