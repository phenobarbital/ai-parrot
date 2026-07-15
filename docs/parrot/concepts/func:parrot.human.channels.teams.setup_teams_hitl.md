---
type: Concept
title: setup_teams_hitl()
id: func:parrot.human.channels.teams.setup_teams_hitl
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Wire the shared HITL bot in one call.
---

# setup_teams_hitl

```python
async def setup_teams_hitl(app: Any, manager: Any, config: TeamsHitlConfig, channel_name: str='teams') -> 'TeamsHumanChannel'
```

Wire the shared HITL bot in one call.

Creates the adapter, GraphClient, Redis connection, and
:class:`TeamsHumanChannel`, registers the webhook route on the
aiohttp app, and registers the channel as ``channel_name`` on
the ``HumanInteractionManager``.

After this call, ``manager.startup()`` will wire the response and
cancel handlers by calling :meth:`TeamsHumanChannel.register_response_handler`
and :meth:`TeamsHumanChannel.register_cancel_handler`.

Args:
    app: The aiohttp ``web.Application`` instance.
    manager: The :class:`~parrot.human.manager.HumanInteractionManager`.
    config: Boot configuration (all creds from navconfig/env vars).
    channel_name: Channel registration key (default ``"teams"``).
        Use ``"teams:my-agent"`` for per-agent override (OQ-9-impl).

Returns:
    The constructed :class:`TeamsHumanChannel` instance.

Example::

    from parrot.human import get_default_human_manager
    from parrot.human.channels.teams import TeamsHitlConfig, setup_teams_hitl

    config = TeamsHitlConfig()   # reads from environment
    manager = get_default_human_manager()
    channel = await setup_teams_hitl(app, manager, config)
    # manager.startup() wires response/cancel handlers; call it after all
    # channels are registered.
