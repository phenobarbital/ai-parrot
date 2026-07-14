---
type: Wiki Summary
title: parrot.services.vault_token_sync
id: mod:parrot.services.vault_token_sync
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: VaultTokenSync — store and retrieve OAuth tokens in the user's navigator
relates_to:
- concept: class:parrot.services.vault_token_sync.VaultTokenSync
  rel: defines
---

# `parrot.services.vault_token_sync`

VaultTokenSync — store and retrieve OAuth tokens in the user's navigator
Vault using a flat ``{provider}:{field}`` key scheme.

Works from non-HTTP contexts (e.g., the Telegram wrapper running under
aiogram polling) by instantiating :class:`navigator_session.vault.SessionVault`
directly via its ``load_for_session`` classmethod.

Example keys stored for a Jira auth:
    jira:access_token
    jira:refresh_token
    jira:cloud_id
    jira:site_url
    jira:account_id

## Classes

- **`VaultTokenSync`** — Persist OAuth tokens in the encrypted user vault.
