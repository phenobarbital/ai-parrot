---
type: Wiki Entity
title: CheckovConfig
id: class:parrot_tools.security.checkov.config.CheckovConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for Checkov IaC security scanner.
relates_to:
- concept: class:parrot_tools.security.base_executor.BaseExecutorConfig
  rel: extends
---

# CheckovConfig

Defined in [`parrot_tools.security.checkov.config`](../summaries/mod:parrot_tools.security.checkov.config.md).

```python
class CheckovConfig(BaseExecutorConfig)
```

Configuration for Checkov IaC security scanner.

Extends BaseExecutorConfig with Checkov-specific options for scanning
Terraform, CloudFormation, Kubernetes, Helm, Dockerfiles, and other
IaC configurations.

Example:
    config = CheckovConfig(
        frameworks=["terraform", "cloudformation"],
        run_checks=["CKV_AWS_18", "CKV_AWS_21"],
        compact=True,
    )
