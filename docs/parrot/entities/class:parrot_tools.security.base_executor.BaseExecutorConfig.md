---
type: Wiki Entity
title: BaseExecutorConfig
id: class:parrot_tools.security.base_executor.BaseExecutorConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base configuration shared by all scanner executors.
---

# BaseExecutorConfig

Defined in [`parrot_tools.security.base_executor`](../summaries/mod:parrot_tools.security.base_executor.md).

```python
class BaseExecutorConfig(BaseModel)
```

Base configuration shared by all scanner executors.

Supports credential configuration for AWS, GCP, and Azure cloud providers.
Credentials can be provided directly or via profile/file references.

AWS credentials default to values from parrot.conf if available.
