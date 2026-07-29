---
type: Wiki Summary
title: parrot.mcp.oauth
id: mod:parrot.mcp.oauth
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.mcp.oauth
relates_to:
- concept: class:parrot.mcp.oauth.InMemoryTokenStore
  rel: defines
- concept: class:parrot.mcp.oauth.NetSuiteM2MAuth
  rel: defines
- concept: class:parrot.mcp.oauth.RedisTokenStore
  rel: defines
- concept: class:parrot.mcp.oauth.TokenStore
  rel: defines
- concept: class:parrot.mcp.oauth.VaultTokenStore
  rel: defines
- concept: mod:parrot.security.vault_utils
  rel: references
---

# `parrot.mcp.oauth`

## Classes

- **`TokenStore`** — Abstract token store interface.
- **`InMemoryTokenStore(TokenStore)`** — Simple in-memory token store (not persistent).
- **`RedisTokenStore(TokenStore)`** — Redis-based token store.
- **`VaultTokenStore(TokenStore)`** — Vault-backed token store that encrypts OAuth tokens using AES-GCM.
- **`NetSuiteM2MAuth`** — OAuth2 Client Credentials (M2M) for NetSuite using certificate-based JWT assertion.
