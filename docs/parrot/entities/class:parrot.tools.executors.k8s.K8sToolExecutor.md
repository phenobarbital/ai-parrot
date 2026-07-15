---
type: Wiki Entity
title: K8sToolExecutor
id: class:parrot.tools.executors.k8s.K8sToolExecutor
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Runs the envelope inside an ephemeral Kubernetes Job.
relates_to:
- concept: class:parrot.tools.executors.abstract.AbstractToolExecutor
  rel: extends
---

# K8sToolExecutor

Defined in [`parrot.tools.executors.k8s`](../summaries/mod:parrot.tools.executors.k8s.md).

```python
class K8sToolExecutor(AbstractToolExecutor)
```

Runs the envelope inside an ephemeral Kubernetes Job.

Args:
    image: Container image that ships ``parrot.cli.tool_worker``.
        Defaults to :data:`parrot.conf.K8S_TOOL_IMAGE`.
    namespace: Kubernetes namespace in which to create the Job.
        Defaults to :data:`parrot.conf.K8S_NAMESPACE`.
    kubeconfig_path: Path to a kubeconfig file. When ``None``, the
        executor first tries in-cluster config (so it works from a
        pod with a ServiceAccount), then falls back to
        ``~/.kube/config``.
    ttl_seconds_after_finished: ``ttlSecondsAfterFinished`` for the
        Job. Defaults to 60s so Kubernetes garbage-collects the pod
        shortly after we read its result.
    resources: Optional ``resources.limits`` / ``requests`` block to
        attach to the pod. Defaults to a small slice
        (``500m`` CPU, ``512Mi`` memory) so unattended tools can't
        balloon the cluster.
    env: Extra environment variables to inject into the pod.
    image_pull_secrets: Names of K8s secrets for private registries.
    service_account: ServiceAccount name the pod runs as.
    labels: Extra labels stamped on the Job/Pod (merged with the
        executor's standard ``parrot-executor=true`` label).
    log_poll_interval_seconds: How often to poll the pod's logs
        while waiting for the worker to finish. Defaults to 1s.

## Methods

- `async def execute(self, envelope: ToolExecutionEnvelope) -> 'ToolResult'`
- `async def close(self) -> None`
