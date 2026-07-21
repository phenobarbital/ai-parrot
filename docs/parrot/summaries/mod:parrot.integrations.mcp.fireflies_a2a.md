---
type: Wiki Summary
title: parrot.integrations.mcp.fireflies_a2a
id: mod:parrot.integrations.mcp.fireflies_a2a
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Fireflies.ai MCP credential adapter for the A2A per-user credential bridge.
relates_to:
- concept: class:parrot.integrations.mcp.fireflies_a2a.FirefliesCredentialResolver
  rel: defines
- concept: mod:parrot.auth.credentials
  rel: references
---

# `parrot.integrations.mcp.fireflies_a2a`

Fireflies.ai MCP credential adapter for the A2A per-user credential bridge.

OQ#6 resolved (2026-06-27 — FEAT-263 / TASK-1648):
Fireflies.ai accepts **exclusively a static API key** from the user. No OAuth
flow is involved. The API key is captured out-of-band (OOB) by directing the
user to a capture page, then stored per-user in vault under ``fireflies:api_key``
via :class:`~parrot.services.vault_token_sync.VaultTokenSync`.

Architecture:
- :class:`FirefliesCredentialResolver`: per-user static-key resolver backed by
  vault (``VaultTokenSync``). First use (key absent) → returns ``None`` and
  surfaces an OOB capture link. After the user submits their key (via
  :meth:`FirefliesCredentialResolver.store_key`), subsequent calls return the key.
- The resolver integrates with :class:`~parrot.a2a.server.A2AServer` via
  :meth:`~parrot.a2a.server.A2AServer.wire_fireflies_resolver`.

Vault key layout::

    fireflies:api_key   → the user's Fireflies.ai API key

Usage::

    from parrot.integrations.mcp.fireflies_a2a import FirefliesCredentialResolver
    from parrot.services.vault_token_sync import VaultTokenSync

    vault = VaultTokenSync(db_pool=app["authdb"], redis=app["redis"])
    resolver = FirefliesCredentialResolver(
        vault_token_sync=vault,
        oob_capture_url="https://your-app.example.com/auth/fireflies/capture",
    )
    a2a_server.wire_fireflies_resolver(resolver)

## Classes

- **`FirefliesCredentialResolver(CredentialResolver)`** — Per-user static API key resolver for the Fireflies.ai MCP server.
