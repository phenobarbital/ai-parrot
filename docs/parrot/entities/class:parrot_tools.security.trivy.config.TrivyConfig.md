---
type: Wiki Entity
title: TrivyConfig
id: class:parrot_tools.security.trivy.config.TrivyConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for Trivy security scanner.
relates_to:
- concept: class:parrot_tools.security.base_executor.BaseExecutorConfig
  rel: extends
---

# TrivyConfig

Defined in [`parrot_tools.security.trivy.config`](../summaries/mod:parrot_tools.security.trivy.config.md).

```python
class TrivyConfig(BaseExecutorConfig)
```

Configuration for Trivy security scanner.

Extends BaseExecutorConfig with Trivy-specific options for vulnerability
scanning, misconfiguration detection, secret scanning, and SBOM generation.

Example:
    config = TrivyConfig(
        severity_filter=["CRITICAL", "HIGH"],
        scanners=["vuln", "secret"],
        ignore_unfixed=True,
    )
