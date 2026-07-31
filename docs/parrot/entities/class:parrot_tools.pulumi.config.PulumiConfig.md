---
type: Wiki Entity
title: PulumiConfig
id: class:parrot_tools.pulumi.config.PulumiConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for Pulumi executor.
relates_to:
- concept: class:parrot_tools.security.base_executor.BaseExecutorConfig
  rel: extends
---

# PulumiConfig

Defined in [`parrot_tools.pulumi.config`](../summaries/mod:parrot_tools.pulumi.config.md).

```python
class PulumiConfig(BaseExecutorConfig)
```

Configuration for Pulumi executor.

Extends BaseExecutorConfig with Pulumi-specific settings for
stack management, state backend, and Docker execution.

Example:
    config = PulumiConfig(
        default_stack="staging",
        auto_create_stack=True,
        state_backend="local",
    )
