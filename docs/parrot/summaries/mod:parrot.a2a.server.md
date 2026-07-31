---
type: Wiki Summary
title: parrot.a2a.server
id: mod:parrot.a2a.server
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: A2A Server - Wraps an AI-Parrot Agent as an A2A-compliant HTTP service.
relates_to:
- concept: class:parrot.a2a.server.A2AEnabledMixin
  rel: defines
- concept: class:parrot.a2a.server.A2AServer
  rel: defines
- concept: mod:parrot.a2a.models
  rel: references
- concept: mod:parrot.a2a.push_notifications
  rel: references
- concept: mod:parrot.auth.broker
  rel: references
- concept: mod:parrot.auth.credentials
  rel: references
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.human.suspended_store
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.a2a.server`

A2A Server - Wraps an AI-Parrot Agent as an A2A-compliant HTTP service.

Identity contract (FEAT-260 / TASK-1643)
-----------------------------------------
Copilot Studio's low-code A2A connection delivers the authenticated end-user's
identity inside the A2A message metadata.  The canonical claim path (in order
of precedence) is:

1. ``message.metadata["user_id"]``             — explicitly set by callers or
                                                  parrot-internal routing.
2. ``message.metadata["from"]["email"]``        — A2A-spec sender object
                                                  (Copilot sets ``from`` dict).
3. ``message.metadata["from"]["id"]``           — fallback when email is absent
                                                  (OID / UPN from Entra token).
4. ``message.metadata["sender"]``               — alternate flat form.
5. ``message.metadata["x-ms-user-email"]``      — Microsoft-injected header
                                                  mirror (some Copilot configs).

If none of these are present the request is rejected — A2AServer never falls
back to a service identity (OQ#1 is resolved: identity IS present in Copilot
A2A messages; absence means an unexpected client).

## Classes

- **`A2AServer`** — Wraps an AI-Parrot Agent (BasicAgent/AbstractBot) as an A2A HTTP service.
- **`A2AEnabledMixin`** — Mixin to add A2A server capabilities to an agent class.
