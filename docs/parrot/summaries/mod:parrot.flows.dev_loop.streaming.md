---
type: Wiki Summary
title: parrot.flows.dev_loop.streaming
id: mod:parrot.flows.dev_loop.streaming
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: FlowStreamMultiplexer — aiohttp WebSocket fan-in for two Redis streams.
relates_to:
- concept: class:parrot.flows.dev_loop.streaming.FlowStreamMultiplexer
  rel: defines
- concept: func:parrot.flows.dev_loop.streaming.flow_stream_ws
  rel: defines
---

# `parrot.flows.dev_loop.streaming`

FlowStreamMultiplexer — aiohttp WebSocket fan-in for two Redis streams.

Implements **Module 3** of the dev-loop spec. The UI (nav-admin Svelte
plugin) consumes a single WebSocket per flow run; the multiplexer fans
in:

* ``flow:{run_id}:flow`` — flow-level events emitted by ``AgentsFlow``.
* ``flow:{run_id}:dispatch:{node_id}`` — per-dispatch events emitted by
  :class:`ClaudeCodeDispatcher`.

Goal (spec G4): the UI never speaks Redis directly. The multiplexer
emits flat JSON envelopes:

.. code-block:: json

    {"source": "flow"|"dispatch", "node_id": str|null,
     "event_kind": str, "ts": float, "payload": {...}}

Query parameters on the WebSocket URL:

* ``view`` — ``"flow" | "dispatch" | "both"`` (default ``"both"``).
* ``replay`` — ``true|false`` (default ``true``).

The handler is intentionally a thin wrapper over
:class:`FlowStreamMultiplexer` so the merge / dispatch-discovery logic is
unit-testable without an aiohttp test server.

## Classes

- **`FlowStreamMultiplexer`** — Merge events from a flow stream and many dispatch streams.

## Functions

- `async def flow_stream_ws(request: web.Request) -> web.WebSocketResponse` — aiohttp WebSocket handler bound to ``GET /api/flow/{run_id}/ws``.
