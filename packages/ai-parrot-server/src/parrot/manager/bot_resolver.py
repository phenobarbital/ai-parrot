"""BotManager-backed bot resolver for the LiveAvatar Phase C worker (FEAT-243).

The standalone LiveKit Agents worker runs in a separate process and resolves
ai-parrot bots by name through a :class:`BotManager` constructed in-process (no
aiohttp app required — ``get_bot`` lazily instantiates ``@register_agent`` bots
from the registry and configures them with ``app=None``).

Usage in the worker entry module (called at import time so ``forkserver``
children re-run it)::

    from parrot.manager.bot_resolver import build_standalone_bot_resolver
    from parrot.integrations.liveavatar.livekit_agent import worker

    worker.configure(bot_resolver=build_standalone_bot_resolver())
    worker.run()
"""

from typing import Awaitable, Callable

from parrot.bots.abstract import AbstractBot
from parrot.manager.manager import BotManager

__all__ = [
    "BotResolver",
    "botmanager_bot_resolver",
    "build_standalone_bot_resolver",
]

#: Async callable resolving an agent name to a bot exposing ``ask_stream``.
BotResolver = Callable[[str], Awaitable[AbstractBot]]


def botmanager_bot_resolver(manager: BotManager) -> BotResolver:
    """Wrap a :class:`BotManager` into an async ``name -> bot`` resolver.

    Resolution is programmatic (``request=None``), so PBAC enforcement is
    skipped — the worker is a trusted server-side process.

    Args:
        manager: A configured (or standalone) ``BotManager``.

    Returns:
        An async resolver that returns the bot or raises ``KeyError`` if the
        name is unknown.
    """

    async def _resolve(name: str) -> AbstractBot:
        bot = await manager.get_bot(name, request=None)
        if bot is None:
            raise KeyError(f"LiveAvatar worker: unknown agent {name!r}")
        return bot

    return _resolve


def build_standalone_bot_resolver(
    *,
    enable_registry_bots: bool = True,
    enable_database_bots: bool = False,
    enable_crews: bool = False,
) -> BotResolver:
    """Build a resolver backed by a fresh, standalone ``BotManager``.

    Suitable for the LiveKit worker process: no aiohttp app, no DB, no Redis
    crews by default. ``@register_agent`` bots are lazily instantiated on first
    resolution.

    Args:
        enable_registry_bots: Load ``@register_agent`` bots from the registry
            (the usual source of named agents). Defaults to ``True``.
        enable_database_bots: Load DB-defined bots (requires a DB). Default off.
        enable_crews: Initialise Redis crew persistence. Default off.

    Returns:
        An async ``name -> bot`` resolver to pass to ``worker.configure``.
    """
    manager = BotManager(
        enable_database_bots=enable_database_bots,
        enable_registry_bots=enable_registry_bots,
        enable_crews=enable_crews,
        enable_swagger_api=False,
    )
    return botmanager_bot_resolver(manager)
