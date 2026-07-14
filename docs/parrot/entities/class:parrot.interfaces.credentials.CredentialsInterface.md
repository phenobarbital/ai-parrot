---
type: Wiki Entity
title: CredentialsInterface
id: class:parrot.interfaces.credentials.CredentialsInterface
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract Base Class for handling credentials and environment variables.
---

# CredentialsInterface

Defined in [`parrot.interfaces.credentials`](../summaries/mod:parrot.interfaces.credentials.md).

```python
class CredentialsInterface(ABC)
```

Abstract Base Class for handling credentials and environment variables.
This class provides methods to process and validate credentials, as well as
retrieve values from environment variables or configuration files.

## Methods

- `def get_env_value(self, key, default: str=None, expected_type: object=None)` — Retrieves a value from the environment variables or the configuration.
- `def processing_credentials(self)`
