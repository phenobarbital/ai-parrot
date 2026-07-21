---
type: Concept
title: load_vault_keys()
id: func:parrot.security.vault_utils.load_vault_keys
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Load vault master keys from the environment.
---

# load_vault_keys

```python
def load_vault_keys() -> tuple[int, bytes, dict[int, bytes]]
```

Load vault master keys from the environment.

Returns:
    Tuple of ``(active_key_id, active_master_key, all_master_keys)``.

Raises:
    RuntimeError: If ``navigator_session.vault.config`` is unavailable.
