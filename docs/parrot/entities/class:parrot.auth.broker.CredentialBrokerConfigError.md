---
type: Wiki Entity
title: CredentialBrokerConfigError
id: class:parrot.auth.broker.CredentialBrokerConfigError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised by :meth:`CredentialBroker.from_config` in strict mode when a
---

# CredentialBrokerConfigError

Defined in [`parrot.auth.broker`](../summaries/mod:parrot.auth.broker.md).

```python
class CredentialBrokerConfigError(Exception)
```

Raised by :meth:`CredentialBroker.from_config` in strict mode when a
resolver cannot be built for a declared provider.

Inherits from ``Exception`` directly so callers can catch it without
depending on any domain-specific base class.
