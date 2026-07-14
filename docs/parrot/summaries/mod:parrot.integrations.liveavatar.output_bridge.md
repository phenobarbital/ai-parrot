---
type: Wiki Summary
title: parrot.integrations.liveavatar.output_bridge
id: mod:parrot.integrations.liveavatar.output_bridge
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Structured-output → AgentChat UI bridge (FEAT-243 / FEAT-249).
relates_to:
- concept: class:parrot.integrations.liveavatar.output_bridge.OutputBridge
  rel: defines
- concept: mod:parrot.integrations.liveavatar.models
  rel: references
---

# `parrot.integrations.liveavatar.output_bridge`

Structured-output → AgentChat UI bridge (FEAT-243 / FEAT-249).

During a chat or voice turn the ai-parrot response bifurcates: plain text is
spoken by the avatar (via ``AvatarTurnSpeaker`` / ``speak_text``), while
structured outputs (charts, data, canvas updates, tool calls) are pushed to the
**existing** AgentChat UI WebSocket channel keyed by ``session_id`` — the same
conversation the avatar is speaking.

The bridge calls ``UserSocketManager.broadcast_to_channel`` (verified at
``packages/ai-parrot-server/src/parrot/handlers/user.py:357``). The socket
manager is dependency-injected (duck-typed) so this module stays free of a hard
import on the ai-parrot-server package and is trivially unit-testable.

For cross-process delivery (multi-worker gunicorn), pass a
:class:`~parrot.integrations.liveavatar.output_transport.RedisBroadcastForwarder`
as the socket manager; see ``output_transport.py``.

## Classes

- **`OutputBridge`** — Publishes structured ai-parrot outputs to the AgentChat UI WS channel.
