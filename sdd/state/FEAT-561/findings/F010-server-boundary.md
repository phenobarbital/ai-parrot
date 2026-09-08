---
id: F010
query_id: Q017
type: read
intent: Server mounting and process ownership need deliberate integration
executed_at: 2026-09-07T05:42:49.930842+00:00
parent_id: null
depth: 1
---

# F010 — Server mounting and process ownership need deliberate integration

## Summary

The manager mounts a default VoiceChatHandler at /ws/voice using lazy imports. The handler has injectable bot_factory/default_config and defaults require_auth=False, so production broadcast provisioning must explicitly bind the intended Nova bot and authenticated owner. output_transport documents Redis pub/sub for structured messages between processes; it does not provide a shared avatar-session registry. Do not serialize live client objects into Redis; discover owner/session metadata across workers and keep sockets with their owner.

## Citations

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 1816-1841
  symbol: `_register_voice_chat_routes`

- path: `packages/ai-parrot-integrations/src/parrot/voice/handler.py`
  lines: 586-644
  symbol: `VoiceChatHandler`

- path: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/output_transport.py`
  lines: 1-35
  symbol: `RedisBroadcastForwarder`
