---
type: Wiki Summary
title: parrot.human.channels.web
id: mod:parrot.human.channels.web
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: WebHumanChannel — delivers HITL interactions over WebSocket.
relates_to:
- concept: class:parrot.human.channels.web.WebHumanChannel
  rel: defines
- concept: mod:parrot.handlers.user
  rel: references
- concept: mod:parrot.human.channels.base
  rel: references
- concept: mod:parrot.human.models
  rel: references
---

# `parrot.human.channels.web`

WebHumanChannel — delivers HITL interactions over WebSocket.

Implements :class:`HumanChannel` using the existing
:class:`~parrot.handlers.user.UserSocketManager` infrastructure to push
``hitl:question`` payloads to the browser over the channel named after
the user's session ID.

The HTTP POST endpoint (:class:`~parrot.handlers.web_hitl.HITLResponseHandler`)
reaches the manager *directly* via ``manager.receive_response()``, so this
channel stores the response callback (required by the ``HumanChannel``
contract) but does not invoke it itself.

## Classes

- **`WebHumanChannel(HumanChannel)`** — Human channel that delivers interactions via WebSocket.
