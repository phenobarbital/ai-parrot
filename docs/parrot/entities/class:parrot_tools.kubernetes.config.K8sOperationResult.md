---
type: Wiki Entity
title: K8sOperationResult
id: class:parrot_tools.kubernetes.config.K8sOperationResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result of a Kubernetes operation.
---

# K8sOperationResult

Defined in [`parrot_tools.kubernetes.config`](../summaries/mod:parrot_tools.kubernetes.config.md).

```python
class K8sOperationResult(BaseModel)
```

Result of a Kubernetes operation.

Contains the outcome of a kubectl-like operation with bounded projections.
Items are simplified dicts — never full Kubernetes API objects — to avoid
flooding the LLM context with raw API responses.

Example:
    result = K8sOperationResult(
        success=True,
        operation="list_pods",
        summary="Found 3 pods in namespace default",
        items=[{"name": "pod-1", "phase": "Running"}],
    )
