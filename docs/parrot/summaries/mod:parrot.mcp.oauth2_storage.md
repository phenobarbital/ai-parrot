---
type: Wiki Summary
title: parrot.mcp.oauth2_storage
id: mod:parrot.mcp.oauth2_storage
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: VaultMCPTokenStorage — adapter bridging MCP SDK's TokenStorage protocol to
relates_to:
- concept: class:parrot.mcp.oauth2_storage.VaultMCPTokenStorage
  rel: defines
- concept: mod:parrot.mcp.oauth
  rel: references
---

# `parrot.mcp.oauth2_storage`

VaultMCPTokenStorage — adapter bridging MCP SDK's TokenStorage protocol to
AI-Parrot's :class:`~parrot.mcp.oauth.VaultTokenStore`.

The MCP SDK expects a ``TokenStorage`` implementation for persisting OAuth2
tokens and client registration information; this adapter delegates all
storage operations to the encrypted Vault infrastructure already used by the
rest of the platform.

Example:
    >>> storage = VaultMCPTokenStorage("user@co.com", "netsuite")
    >>> await storage.set_tokens(token)
    >>> token = await storage.get_tokens()

## Classes

- **`VaultMCPTokenStorage(TokenStorage)`** — MCP SDK ``TokenStorage`` adapter backed by AI-Parrot's Vault.
