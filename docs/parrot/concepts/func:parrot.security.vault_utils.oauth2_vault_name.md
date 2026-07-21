---
type: Concept
title: oauth2_vault_name()
id: func:parrot.security.vault_utils.oauth2_vault_name
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build the deterministic Vault credential name for an OAuth2 token.
---

# oauth2_vault_name

```python
def oauth2_vault_name(provider_id: str, channel: str, user_id: str) -> str
```

Build the deterministic Vault credential name for an OAuth2 token.

Mirrors :data:`parrot.auth.oauth2_base._VAULT_NAME_TEMPLATE` so the
namespace stays consistent across writers and readers.
