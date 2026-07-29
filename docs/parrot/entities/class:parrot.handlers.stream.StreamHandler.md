---
type: Wiki Entity
title: StreamHandler
id: class:parrot.handlers.stream.StreamHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Streaming Endpoints for Parrot LLM Responses.
---

# StreamHandler

Defined in [`parrot.handlers.stream`](../summaries/mod:parrot.handlers.stream.md).

```python
class StreamHandler(BaseHandler)
```

Streaming Endpoints for Parrot LLM Responses.

Supports:
- SSE (Server-Sent Events)
- WebSockets
- NDJSON
- Chunked transfer encoding

## Methods

- `async def stream_sse(self, request: web.Request) -> web.StreamResponse` — Server-Sent Events (SSE) streaming endpoint
- `async def stream_ndjson(self, request: web.Request) -> web.StreamResponse` — NDJSON (Newline Delimited JSON) streaming endpoint
- `async def stream_chunked(self, request: web.Request) -> web.StreamResponse` — Plain chunked transfer encoding
- `async def stream_websocket(self, request: web.Request) -> web.WebSocketResponse` — WebSocket endpoint for bidirectional streaming
- `async def broadcast(self, message: dict)` — Broadcast message to all connected clients
- `def configure_routes(self, app: web.Application)` — Configure routes for streaming endpoints.
