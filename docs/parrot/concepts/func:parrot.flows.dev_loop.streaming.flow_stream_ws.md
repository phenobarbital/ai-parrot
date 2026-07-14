---
type: Concept
title: flow_stream_ws()
id: func:parrot.flows.dev_loop.streaming.flow_stream_ws
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: aiohttp WebSocket handler bound to ``GET /api/flow/{run_id}/ws``.
---

# flow_stream_ws

```python
async def flow_stream_ws(request: web.Request) -> web.WebSocketResponse
```

aiohttp WebSocket handler bound to ``GET /api/flow/{run_id}/ws``.

Query parameters:

* ``view`` — ``"flow" | "dispatch" | "both"`` (default ``"both"``).
* ``replay`` — ``true|false`` (default ``true``).

Emits a JSON envelope per event:

.. code-block:: json

    {"source": "flow"|"dispatch", "node_id": str|null,
     "event_kind": str, "ts": float, "payload": {...}}

The owning aiohttp app must populate ``request.app["redis_url"]``
(or ``request.app["redis"]`` with a pre-built client). The handler
closes both the Redis connection it created and the WebSocket on
client disconnect.
