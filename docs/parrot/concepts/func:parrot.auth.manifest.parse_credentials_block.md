---
type: Concept
title: parse_credentials_block()
id: func:parrot.auth.manifest.parse_credentials_block
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse a raw ``credentials:`` list (already parsed from YAML) into configs.
---

# parse_credentials_block

```python
def parse_credentials_block(block: Optional[List[Dict[str, Any]]], *, expand_env: bool=True) -> List[ProviderCredentialConfig]
```

Parse a raw ``credentials:`` list (already parsed from YAML) into configs.

Args:
    block: List of raw dicts (the value of the ``credentials:`` YAML key).
        ``None`` and empty list are accepted and return ``[]``.
    expand_env: When ``True`` (default), expand ``${VAR}`` / ``${VAR:-default}``
        substitutions in option string values.

Returns:
    Parsed list of :class:`ProviderCredentialConfig`.

Raises:
    ValueError: If *block* is not a list.
