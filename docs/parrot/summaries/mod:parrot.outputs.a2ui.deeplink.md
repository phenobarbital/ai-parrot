---
type: Wiki Summary
title: parrot.outputs.a2ui.deeplink
id: mod:parrot.outputs.a2ui.deeplink
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Deep-link token service (Module 8, goal G6).
relates_to:
- concept: class:parrot.outputs.a2ui.deeplink.DeepLinkError
  rel: defines
- concept: class:parrot.outputs.a2ui.deeplink.DeepLinkExpiredError
  rel: defines
- concept: class:parrot.outputs.a2ui.deeplink.DeepLinkService
  rel: defines
- concept: class:parrot.outputs.a2ui.deeplink.ResumePayload
  rel: defines
- concept: mod:parrot.outputs.a2ui.artifacts
  rel: references
---

# `parrot.outputs.a2ui.deeplink`

Deep-link token service (Module 8, goal G6).

`requires_actions` components on static (baked) surfaces cannot dispatch actions in v1
(no ActionRouter — FEAT-B). Each action degrades to a **single-use, TTL-bound deep
link**: clicking it resumes the originating channel/session and injects the action as a
structured user message.

Token strategy (spec §8): navigator_auth exposes a JWT `create_token` mint, but binding
core to it would violate the one-way import rule (G8). This service therefore uses the
**pre-approved Redis opaque one-shot token** — an opaque `secrets.token_urlsafe(32)` id
whose server-side payload (session/user/agent/channel/action) is stored in Redis with a
TTL and deleted on first consume. The URL embeds ONLY the opaque id — never the payload
(spec §7). The Redis consume record is exactly the single-use/replay guard the spec
mandates regardless of mint source.

Copies the one-shot nonce machinery of ``parrot.auth.oauth2_base`` (key template,
``token_urlsafe(32)``, TTL ``set``, ``get`` → ``delete`` one-shot consume).

## Classes

- **`DeepLinkError(Exception)`** — Base class for deep-link errors.
- **`DeepLinkExpiredError(DeepLinkError)`** — Raised when a token is missing, expired, or already consumed (single-use).
- **`ResumePayload(BaseModel)`** — Server-side payload restored when a deep link is consumed.
- **`DeepLinkService`** — Mints and consumes single-use, TTL-bound deep-link tokens.
