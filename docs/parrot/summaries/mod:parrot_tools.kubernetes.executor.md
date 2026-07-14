---
type: Wiki Summary
title: parrot_tools.kubernetes.executor
id: mod:parrot_tools.kubernetes.executor
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: KubernetesExecutor — async Kubernetes client wrapper.
relates_to:
- concept: class:parrot_tools.kubernetes.executor.KubernetesExecutor
  rel: defines
- concept: mod:parrot_tools.kubernetes.config
  rel: references
---

# `parrot_tools.kubernetes.executor`

KubernetesExecutor — async Kubernetes client wrapper.

Wraps kubernetes_asyncio to provide kubectl-like operations for AI agents.
Returns bounded K8sOperationResult projections; never dumps raw API objects.

Mirrors PulumiExecutor pattern but is standalone (does not inherit
BaseExecutor because that is oriented toward Docker/CLI subprocess execution).

kubernetes_asyncio is lazy-imported to avoid cost when the toolkit is not
used. See K8sToolExecutor (parrot/tools/executors/k8s.py) for the same pattern.

## Classes

- **`KubernetesExecutor`** — Async Kubernetes client wrapper.
