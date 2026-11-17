---
id: F021
query_id: Q041
type: read
intent: "R4: read UserSocketManager — send to one user's sockets, Redis PubSub cross-process."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-022]
---

# F021 — UserSocketManager keeps per-process user_sockets[username] sets, JWT auth, Redis for user-info storage and channel pubsub; send_direct_message targets a username's open sockets in THIS process only

## Summary

`parrot/handlers/user.py` (709 lines, server). Extends navigator `WebSocketManager`. State: `user_sockets: Dict[str, Set[WebSocketResponse]]` keyed by *username* (from JWT `_validate_token`, which maps `user_id = payload.get("user_id", payload.get("sub"))`), `channel_subscriptions`, `pubsub_tasks`. `_on_startup` creates a Redis pool and registers default channels. `send_direct_message(from_username, to_username, content)` iterates `self.user_sockets.get(to_username)` — local dict, no Redis publish. `broadcast_to_channel` also iterates local lists. Redis is used for `_store_user_info` and (via parent) channel pubsub; no 'send to user across processes' primitive found.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/user.py`
  lines: 100-110
  symbol: `UserSocketManager.__init__`
  excerpt: |
    self.authenticated_users: Dict[web.WebSocketResponse, Dict[str, Any]] = {}
    self.user_sockets: Dict[str, Set[web.WebSocketResponse]] = {}
    self.pubsub_tasks: List[asyncio.Task] = []
    self.channel_subscriptions: Dict[str, List[web.WebSocketResponse]] = {}
- path: `packages/ai-parrot-server/src/parrot/handlers/user.py`
  lines: 179-217
  symbol: `UserSocketManager._validate_token`
  excerpt: |
    "user_id": payload.get("user_id", payload.get("sub"))
- path: `packages/ai-parrot-server/src/parrot/handlers/user.py`
  lines: 219-262
  symbol: `UserSocketManager._handle_auth`
  excerpt: |
    self.user_sockets.setdefault(username, set()).add(ws)
- path: `packages/ai-parrot-server/src/parrot/handlers/user.py`
  lines: 382-414
  symbol: `UserSocketManager.send_direct_message`
  excerpt: |
    target_sockets = self.user_sockets.get(to_username, set())
    open_sockets = [ws for ws in target_sockets if not ws.closed]
- path: `packages/ai-parrot-server/src/parrot/handlers/user.py`
  lines: 340-360
  symbol: `UserSocketManager.broadcast_to_channel`
  excerpt: |
    for ws in self.channel_subscriptions[channel]: await ws.send_str(...)

## Notes

Spike S3: a per-principal send exists (`send_direct_message` by username) but is process-local; sockets are keyed by *username*, not nav user_id. Cross-process delivery would need a Redis channel the manager already has infrastructure for (pubsub_tasks) — needs verification of the parent `WebSocketManager.register_channel` (navigator package, not in repo). [cross-lane: type=wiki_query, intent=navigator.services.ws WebSocketManager register_channel pubsub semantics]
