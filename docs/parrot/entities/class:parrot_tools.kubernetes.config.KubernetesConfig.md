---
type: Wiki Entity
title: KubernetesConfig
id: class:parrot_tools.kubernetes.config.KubernetesConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for KubernetesExecutor.
---

# KubernetesConfig

Defined in [`parrot_tools.kubernetes.config`](../summaries/mod:parrot_tools.kubernetes.config.md).

```python
class KubernetesConfig(BaseModel)
```

Configuration for KubernetesExecutor.

Supports both in-cluster (service account) and kubeconfig-based authentication.
Mirrors PulumiConfig pattern but stands alone (no Docker/CLI inheritance).

Example:
    # Default in-cluster config
    cfg = KubernetesConfig(in_cluster=True)

    # Kubeconfig with specific context
    cfg = KubernetesConfig(
        kubeconfig_path="/home/user/.kube/config",
        context="minikube",
        namespace="production",
    )
