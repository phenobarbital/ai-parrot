"""OpenAI Codex-backed agent target for the Agent CLI Daemon (agentd).

Serves an :class:`~parrot.bots.agent.Agent` whose LLM is an
:class:`~parrot.clients.openai.codex_agent.OpenAICodexClient`, so turns can be
delegated to the local Codex runtime authenticated with the credentials the
``codex`` CLI already has installed.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..bots.agent import Agent

__all__ = ["make_agent", "sanitize_codex_environment"]

_AUTH_OVERRIDE_VARS = ("CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_API_KEY")


def sanitize_codex_environment(force_local_auth: bool = True) -> dict[str, list[str]]:
    """Remove env entries that break or override the spawned Codex runtime.

    Args:
        force_local_auth: When ``True`` (the default), drop environment
            variables that can make Codex prefer an API key/token over the
            credentials stored by the installed Codex CLI.

    Returns:
        Mapping with ``invalid`` env names and dropped ``auth`` override names.
    """
    invalid = [name for name in os.environ if not name.replace("_", "").isalnum()]
    for name in invalid:
        os.environ.pop(name, None)

    auth: list[str] = []
    if force_local_auth:
        for name in _AUTH_OVERRIDE_VARS:
            if os.environ.pop(name, None) is not None:
                auth.append(name)

    return {"invalid": invalid, "auth": auth}


def make_agent(force_local_auth: bool | None = None, **kwargs: Any) -> Agent:
    """Build a Codex-backed agent for ``parrot serve``.

    Pass ``llm="openai-codex:<model>"`` or ``llm="codex-agent:<model>"`` in
    the agent kwargs so the bot resolves :class:`OpenAICodexClient`.
    """
    if force_local_auth is None:
        force_local_auth = os.environ.get("PARROT_CODEX_USE_LOCAL_AUTH", "1") != "0"

    dropped = sanitize_codex_environment(force_local_auth=force_local_auth)

    from ..bots.agent import Agent

    agent = Agent(**kwargs)
    agent.logger.info(
        "codex-code agent target ready (dropped %d invalid env names, "
        "auth vars dropped: %s)",
        len(dropped["invalid"]),
        dropped["auth"] or "none",
    )

    surviving = [name for name in _AUTH_OVERRIDE_VARS if name in os.environ]
    if surviving:
        agent.logger.warning(
            "%s still set: spawned Codex turns may use that credential instead "
            "of the installed Codex login.",
            " and ".join(surviving),
        )
    return agent
