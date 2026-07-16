---
type: Wiki Entity
title: KubernetesExecutor
id: class:parrot_tools.kubernetes.executor.KubernetesExecutor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Async Kubernetes client wrapper.
---

# KubernetesExecutor

Defined in [`parrot_tools.kubernetes.executor`](../summaries/mod:parrot_tools.kubernetes.executor.md).

```python
class KubernetesExecutor
```

Async Kubernetes client wrapper.

Wraps kubernetes_asyncio (CoreV1Api, AppsV1Api) to implement read and
mutating operations, returning bounded K8sOperationResult projections.

kubernetes_asyncio is lazy-imported inside _ensure_client() to avoid
import-time cost when the package is not installed.

Example:
    config = KubernetesConfig(namespace="production")
    executor = KubernetesExecutor(config)
    result = await executor.list_pods()
    await executor.close()

## Methods

- `async def close(self) -> None` — Close the API client to release connections.
- `async def list_pods(self, namespace: Optional[str]=None, label_selector: Optional[str]=None) -> K8sOperationResult` — List pods in a namespace with optional label filtering.
- `async def get_logs(self, pod: str, namespace: Optional[str]=None, container: Optional[str]=None, tail_lines: int=200) -> K8sOperationResult` — Get logs from a pod, optionally from a specific container.
- `async def describe(self, kind: str, name: str, namespace: Optional[str]=None) -> K8sOperationResult` — Describe a Kubernetes resource (kubectl describe equivalent).
- `async def get_resources(self, kind: str, namespace: Optional[str]=None, label_selector: Optional[str]=None) -> K8sOperationResult` — List Kubernetes resources by kind with optional label filtering.
- `async def apply_manifest(self, manifest_yaml: str, namespace: Optional[str]=None) -> K8sOperationResult` — Create Kubernetes resources from a manifest YAML string.
- `async def scale_deployment(self, name: str, replicas: int, namespace: Optional[str]=None) -> K8sOperationResult` — Scale a Deployment to the specified number of replicas.
- `async def delete_resource(self, kind: str, name: str, namespace: Optional[str]=None) -> K8sOperationResult` — Delete a Kubernetes resource by kind and name.
- `async def rollout_restart(self, name: str, namespace: Optional[str]=None) -> K8sOperationResult` — Restart a Deployment by patching its pod template annotation.
