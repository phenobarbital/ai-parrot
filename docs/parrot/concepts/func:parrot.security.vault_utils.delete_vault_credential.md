---
type: Concept
title: delete_vault_credential()
id: func:parrot.security.vault_utils.delete_vault_credential
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Hard-delete a Vault credential from DocumentDB.
---

# delete_vault_credential

```python
async def delete_vault_credential(user_id: str, vault_name: str) -> None
```

Hard-delete a Vault credential from DocumentDB.

Args:
    user_id: Owner's user identifier.
    vault_name: Vault credential name to remove.
