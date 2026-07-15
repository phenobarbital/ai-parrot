---
type: Wiki Summary
title: parrot_tools.security.base_executor
id: mod:parrot_tools.security.base_executor
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base executor for running CLI-based security scanners.
relates_to:
- concept: class:parrot_tools.security.base_executor.BaseExecutor
  rel: defines
- concept: class:parrot_tools.security.base_executor.BaseExecutorConfig
  rel: defines
- concept: mod:parrot.conf
  rel: references
---

# `parrot_tools.security.base_executor`

Base executor for running CLI-based security scanners.

Provides a reusable abstraction for running security scanners via Docker
or direct process execution. All scanner executors (Prowler, Trivy, Checkov)
inherit from this base class.

## Classes

- **`BaseExecutorConfig(BaseModel)`** — Base configuration shared by all scanner executors.
- **`BaseExecutor(ABC)`** — Abstract base executor for Docker or CLI process management.
