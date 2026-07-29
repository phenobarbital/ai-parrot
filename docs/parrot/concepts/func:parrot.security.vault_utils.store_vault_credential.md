---
type: Concept
title: store_vault_credential()
id: func:parrot.security.vault_utils.store_vault_credential
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Encrypt and upsert secret parameters in the Vault.
---

# store_vault_credential

```python
async def store_vault_credential(user_id: str, vault_name: str, secret_params: Dict[str, Any]) -> None
```

Encrypt and upsert secret parameters in the Vault.

Stores the credential under the compound key ``(user_id, vault_name)``
in the ``user_credentials`` collection.  If a document with that key
already exists it is updated; otherwise a new document is inserted.

Args:
    user_id: Owner's user identifier.
    vault_name: Deterministic credential name (e.g. ``"mcp_perplexity_agent-1"``).
    secret_params: Dict of secret values to encrypt (e.g. ``{"api_key": "sk-..."}``)

Raises:
    RuntimeError: If vault keys are unavailable.
