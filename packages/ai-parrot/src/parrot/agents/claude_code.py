"""Claude Code-backed agent target for the Agent CLI Daemon (agentd).

Serves an :class:`~parrot.bots.agent.Agent` whose LLM is a
:class:`~parrot.clients.anthropic.claude_agent.ClaudeAgentClient`, so every turn is
delegated to a local Claude Code sub-agent authenticated with the
credentials the bundled ``claude`` CLI already holds (``claude auth`` /
claude.ai login) rather than an ``ANTHROPIC_API_KEY``.

Usage::

    PARROT_CLAUDE_USE_CC_AUTH=1 parrot serve examples/agents/claude_code_daemon.yaml
    parrot ask claude-code "What is 2 + 2?"
    parrot attach claude-code

Two environment hazards this factory works around — both are properties of
how ai-parrot boots, not of ``claude-agent-sdk``:

1. Importing ``parrot`` loads the navconfig ``settings/`` tree into
   ``os.environ``, which injects the INI *section headers* (``[aws]``,
   ``[google]``, …) as environment variable **names**. The bundled Node
   ``claude`` CLI refuses to start with those present, and the SDK
   surfaces it only as an empty ``CLIConnectionError: Failed to start
   Claude Code:``. :func:`sanitize_claude_environment` strips them.

2. The same settings tree usually exports ``ANTHROPIC_API_KEY``, and the
   CLI gives an API key precedence over the claude.ai login — billing
   would silently move to the API key. This target therefore drops the
   API-key variables **by default** so the Claude Code credentials win.
   The CLI confirms the choice in its ``init`` message:
   ``apiKeySource: "none"`` plus a ``five_hour`` rate-limit event means
   the claude.ai login; ``apiKeySource: "ANTHROPIC_API_KEY"`` means a key
   took over. Set ``PARROT_CLAUDE_USE_CC_AUTH=0`` (or
   ``force_cc_auth=False``) to bill an API key instead.

Note:
    Order matters. Sanitising must happen *after* ``parrot`` has been
    imported (and therefore after navconfig has populated
    ``os.environ``), which is why it runs inside :func:`make_agent` rather
    than at module import time.

FEAT-434 (Claude Agent Tool Bridge): this factory is the reference
integration `parrot serve` exercises for the bridged-HITL wiring
(TASK-2290). The daemon (``AgentDaemon._configure_hitl``,
``parrot.integrations.agentd.service``) attaches a ``ConfirmationGuard``
to whatever agent ``make_agent()`` returns — nothing here has to build
one itself. Any confirming tool the agent registers is therefore already
bridged through the real HITL channel (never Telegram, never
self-granted) once served this way.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..bots.agent import Agent

__all__ = ["make_agent", "sanitize_claude_environment"]

#: Env vars that make the ``claude`` CLI prefer an API key over the
#: claude.ai / Claude Code login.
_AUTH_OVERRIDE_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def sanitize_claude_environment(force_cc_auth: bool = True) -> dict[str, list[str]]:
    """Remove env entries that break (or hijack) the bundled ``claude`` CLI.

    Args:
        force_cc_auth: When ``True`` (the default), also drop the API-key
            variables so the CLI falls back to its stored claude.ai /
            Claude Code login. Pass ``False`` to bill an API key instead.

    Returns:
        Mapping with two keys: ``invalid`` — names dropped for being
        unusable as environment variable names — and ``auth`` — API-key
        variables dropped to force Claude Code credentials.
    """
    invalid = [name for name in os.environ if not name.replace("_", "").isalnum()]
    for name in invalid:
        os.environ.pop(name, None)

    auth: list[str] = []
    if force_cc_auth:
        for name in _AUTH_OVERRIDE_VARS:
            if os.environ.pop(name, None) is not None:
                auth.append(name)

    return {"invalid": invalid, "auth": auth}


def make_agent(force_cc_auth: bool | None = None, **kwargs: Any) -> Agent:
    """Build a Claude Code-backed agent for ``parrot serve``.

    Sanitises the environment, then constructs the agent. Pass
    ``llm="claude-agent:<model>"`` (or ``"claude-code:<model>"``) so the
    bot resolves a :class:`ClaudeAgentClient`; any other ``llm`` value
    yields an ordinary agent and the Claude Code delegation is lost.

    Args:
        force_cc_auth: Whether to drop ``ANTHROPIC_API_KEY`` /
            ``ANTHROPIC_AUTH_TOKEN`` so the CLI uses its Claude Code
            login. ``None`` (the default) reads
            ``PARROT_CLAUDE_USE_CC_AUTH``, which itself defaults to on —
            set it to ``"0"`` to bill an API key instead.
        **kwargs: Forwarded verbatim to :class:`~parrot.bots.agent.Agent`
            (``name``, ``llm``, ``system_prompt``, …). Supplied by the
            agentd YAML's ``agent.kwargs``.

    Returns:
        A configured :class:`~parrot.bots.agent.Agent`. ``parrot serve``
        awaits its ``configure()`` afterwards, which is where the LLM
        client is actually instantiated.
    """
    if force_cc_auth is None:
        force_cc_auth = os.environ.get("PARROT_CLAUDE_USE_CC_AUTH", "1") != "0"

    dropped = sanitize_claude_environment(force_cc_auth=force_cc_auth)

    from ..bots.agent import Agent

    agent = Agent(**kwargs)
    agent.logger.info(
        "claude-code agent target ready (dropped %d invalid env names, "
        "auth vars dropped: %s)",
        len(dropped["invalid"]),
        dropped["auth"] or "none",
    )

    # FEAT-434: surface whether this target carries any confirming tools,
    # so an operator serving it under agentd knows up front whether the
    # bridged-HITL wiring (TASK-2290) will ever actually be exercised for
    # this agent — the guard itself is attached generically by
    # `AgentDaemon._configure_hitl`, not here.
    tool_manager = getattr(agent, "tool_manager", None)
    if tool_manager is not None:
        confirming = [
            tool
            for tool in tool_manager.get_all_tools()
            if (getattr(tool, "routing_meta", None) or {}).get("requires_confirmation")
        ]
        agent.logger.debug(
            "claude-code agent target: %d confirming tool(s) registered "
            "(bridged-HITL wiring applies once served under agentd).",
            len(confirming),
        )

    # A surviving API key silently outranks the claude.ai login inside the
    # spawned CLI, so say so loudly rather than let billing move quietly.
    surviving = [n for n in _AUTH_OVERRIDE_VARS if n in os.environ]
    if surviving:
        agent.logger.warning(
            "%s still set: the spawned claude CLI will report "
            "apiKeySource=%s and bill that key instead of the Claude Code "
            "login. Unset it, or leave force_cc_auth enabled.",
            " and ".join(surviving),
            surviving[0],
        )
    return agent
