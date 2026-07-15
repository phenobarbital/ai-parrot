---
type: Wiki Summary
title: parrot.core.ws_auth
id: mod:parrot.core.ws_auth
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: WebSocket / token authentication infrastructure.
relates_to:
- concept: class:parrot.core.ws_auth.AuthenticatedUser
  rel: defines
- concept: class:parrot.core.ws_auth.TokenValidator
  rel: defines
---

# `parrot.core.ws_auth`

WebSocket / token authentication infrastructure.

Shared, dependency-light auth primitives for any AI-Parrot service that needs
to authenticate connections — typically WebSocket transports that validate a
JWT from the ``Sec-WebSocket-Protocol`` subprotocol or a first ``auth`` message
(browsers cannot set an ``Authorization`` header on a WebSocket).

This module lives in ``parrot.core`` precisely so it carries **no hard
dependencies** on any concrete service (voice bots, form designer, etc.). It
imports only the standard library, ``navconfig.logging`` and — lazily, inside
``validate()`` — ``jwt`` / ``navigator_auth``. Consumers:

- ``parrot.voice.handler`` (VoiceChatHandler) — re-exports for backward compat.
- ``parrot_formdesigner`` audio-form WebSocket handler.
- any future WS service requiring authentication.

## Classes

- **`AuthenticatedUser`** — Represents an authenticated user from a JWT token.
- **`TokenValidator`** — JWT Token validator.
