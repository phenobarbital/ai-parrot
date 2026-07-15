---
type: Concept
title: retrieve_vault_credential()
id: func:parrot.security.vault_utils.retrieve_vault_credential
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Decrypt and return a secret credential from the Vault.
---

# retrieve_vault_credential

```python
async def retrieve_vault_credential(user_id: str, vault_name: str) -> Dict[str, Any]
```

Decrypt and return a secret credential from the Vault.

Args:
    user_id: Owner's user identifier.
    vault_name: Vault credential name.

Returns:
    Decrypted dict of secret parameters.

Raises:
    KeyError: If the credential is not found in the Vault.
    RuntimeError: If vault keys are unavailable.
