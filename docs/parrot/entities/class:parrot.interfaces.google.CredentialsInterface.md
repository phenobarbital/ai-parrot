---
type: Wiki Entity
title: CredentialsInterface
id: class:parrot.interfaces.google.CredentialsInterface
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mixin for processing credentials with environment variable replacement.
---

# CredentialsInterface

Defined in [`parrot.interfaces.google`](../summaries/mod:parrot.interfaces.google.md).

```python
class CredentialsInterface
```

Mixin for processing credentials with environment variable replacement.

Handles ${VAR_NAME} patterns in credential dictionaries.

## Methods

- `def processing_credentials(self) -> None` — Process credentials dictionary and replace environment variables.
