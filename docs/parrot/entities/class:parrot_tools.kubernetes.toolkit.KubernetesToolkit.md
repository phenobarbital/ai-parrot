---
type: Wiki Entity
title: KubernetesToolkit
id: class:parrot_tools.kubernetes.toolkit.KubernetesToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Kubernetes cluster management toolkit.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# KubernetesToolkit

Defined in [`parrot_tools.kubernetes.toolkit`](../summaries/mod:parrot_tools.kubernetes.toolkit.md).

```python
class KubernetesToolkit(AbstractToolkit)
```

Kubernetes cluster management toolkit.

Exposes kubectl-like operations as agent tools. Each public async method
with prefix k8s_ is automatically discovered by AbstractToolkit.get_tools()
and returned as a separate tool.

Read operations (no grant required):
    - k8s_list_pods: List pods in a namespace
    - k8s_get_logs: Get logs from a pod
    - k8s_describe: Describe a Kubernetes resource
    - k8s_get: List resources by kind

Mutating operations (requires_grant=True via routing_meta — FEAT-211):
    - k8s_apply_manifest: Apply a YAML manifest
    - k8s_scale_deployment: Scale a deployment's replicas
    - k8s_delete_resource: Delete a Kubernetes resource
    - k8s_rollout_restart: Restart a deployment (rolling)

Example:
    toolkit = KubernetesToolkit(config=KubernetesConfig(namespace="prod"))
    tools = toolkit.get_tools()
    agent = Agent(tools=tools)

## Methods

- `async def close(self) -> None` — Close the underlying Kubernetes API client.
- `async def k8s_list_pods(self, namespace: Optional[str]=None, label_selector: Optional[str]=None) -> K8sOperationResult` — List pods in a namespace with optional label selector filtering.
- `async def k8s_get_logs(self, pod: str, namespace: Optional[str]=None, container: Optional[str]=None, tail_lines: int=200) -> K8sOperationResult` — Get logs from a pod, optionally from a specific container.
- `async def k8s_describe(self, kind: str, name: str, namespace: Optional[str]=None) -> K8sOperationResult` — Describe a Kubernetes resource (kubectl describe equivalent).
- `async def k8s_get(self, kind: str, namespace: Optional[str]=None, label_selector: Optional[str]=None) -> K8sOperationResult` — List Kubernetes resources by kind with optional label filtering.
- `async def k8s_apply_manifest(self, manifest_yaml: str, namespace: Optional[str]=None) -> K8sOperationResult` — Apply a Kubernetes manifest YAML string to the cluster.
- `async def k8s_scale_deployment(self, name: str, replicas: int, namespace: Optional[str]=None) -> K8sOperationResult` — Scale a Deployment to the specified number of replicas.
- `async def k8s_delete_resource(self, kind: str, name: str, namespace: Optional[str]=None) -> K8sOperationResult` — Delete a Kubernetes resource by kind and name.
- `async def k8s_rollout_restart(self, name: str, namespace: Optional[str]=None) -> K8sOperationResult` — Restart a Deployment by patching its pod template annotation.
