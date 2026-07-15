---
type: Wiki Summary
title: parrot.handlers.liveavatar_output
id: mod:parrot.handlers.liveavatar_output
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Server-side wiring for the Redis structured-output transport (FEAT-249).
relates_to:
- concept: func:parrot.handlers.liveavatar_output.configure_liveavatar_output_subscriber
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.integrations.liveavatar.output_transport
  rel: references
---

# `parrot.handlers.liveavatar_output`

Server-side wiring for the Redis structured-output transport (FEAT-249).

Structured outputs (charts/data/canvas/tool_calls) produced by any ai-parrot
worker process are published to a Redis pub/sub channel via
``RedisBroadcastForwarder``. This module runs the **consumer** side inside the
ai-parrot-server: a background task that re-broadcasts each envelope through the
app's ``UserSocketManager`` so it reaches the browser AgentChat UI on the channel
keyed by ``session_id``.

Opt-in (mirrors ``configure_job_manager``): call
:func:`configure_liveavatar_output_subscriber` during app assembly when the Redis
structured-output transport is enabled (``ENABLE_STRUCTURED_OUTPUT_TRANSPORT``).
The Redis URL and channel **must match** the publisher's ``RedisBroadcastForwarder``
(both default to ``parrot.conf.REDIS_URL`` and ``liveavatar:structured-outputs``).

## Functions

- `def configure_liveavatar_output_subscriber(app: web.Application, *, redis_url: Optional[str]=None, channel: Optional[str]=None) -> web.Application` — Register the LiveAvatar output subscriber on the aiohttp application.
