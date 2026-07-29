---
type: Concept
title: load_credentials_manifest()
id: func:parrot.auth.manifest.load_credentials_manifest
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Load credential provider configs from a YAML file.
---

# load_credentials_manifest

```python
def load_credentials_manifest(source: Union[str, Path], *, key: str='credentials') -> List[ProviderCredentialConfig]
```

Load credential provider configs from a YAML file.

Args:
    source: Absolute or relative path to the YAML manifest file.
    key: Top-level YAML key that holds the list.  Defaults to
        ``"credentials"``.

Returns:
    Parsed list of :class:`ProviderCredentialConfig` entries.
    Returns an empty list if the file does not exist or the key is absent.

Raises:
    ImportError: If PyYAML is not installed.
    ValueError: If the YAML structure under *key* is not a list.
