---
id: F009
query_id: Q011
type: grep
intent: Identify the aiohttp handler/route registration convention for serving endpoints
executed_at: 2026-06-08T23:40:00Z
depth: 0
---

# F009 — Route registration convention + a separate WS infra for the web channel

## Summary

Core handlers register via a module-level `setup(app)` calling
`app.router.add_route(...)` (e.g. `dataset_filter_handler.py`,
`spatial_filter_handler.py`), and `VoiceChatHandler.setup_routes(app, prefix)`
follows the same pattern with `app.router.add_get('/ws/voice', ...)`. Separately,
`human/channels/web.py::WebHumanChannel` delivers HITL over a `UserSocketManager`
abstraction (pub/sub to a per-user/session WS channel) — a *different* WS
mechanism than `VoiceChatHandler`'s direct `web.WebSocketResponse`. The voice
feature should reuse the `VoiceChatHandler` direct-WS style (binary/b64 audio
frames), not the HITL pub/sub channel.

## Citations

- path: `packages/ai-parrot/src/parrot/handlers/dataset_filter_handler.py`
  lines: 21-23
  excerpt: |
    app.router.add_route("*", "/api/v1/filters/{agent_id}", DatasetFilterHandler)

- path: `packages/ai-parrot-integrations/src/parrot/voice/handler.py`
  lines: 398-449
  symbol: `VoiceChatHandler.setup_routes`
  excerpt: |
    app.router.add_get(self.ws_route, self.handle_websocket)   # /ws/voice
    app.router.add_get(self.health_route, self._handle_health)

- path: `packages/ai-parrot/src/parrot/human/channels/web.py`
  lines: 26-72
  symbol: `WebHumanChannel.send_interaction`
  excerpt: |
    # publishes via UserSocketManager to a per-session WS channel (HITL only)

## Notes

A new AgentTalk voice endpoint slots in as `setup_routes(app)` on a handler,
identical to how `VoiceChatHandler` already mounts `/ws/voice`.
