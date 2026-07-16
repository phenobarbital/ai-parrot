---
type: Wiki Summary
title: parrot_tools.kubernetes.toolkit
id: mod:parrot_tools.kubernetes.toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: KubernetesToolkit — AbstractToolkit exposing kubectl-like agent tools.
relates_to:
- concept: class:parrot_tools.kubernetes.toolkit.KubernetesToolkit
  rel: defines
- concept: mod:parrot_tools.kubernetes.config
  rel: references
- concept: mod:parrot_tools.kubernetes.executor
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.kubernetes.toolkit`

KubernetesToolkit — AbstractToolkit exposing kubectl-like agent tools.

Mirrors PulumiToolkit pattern: inherits AbstractToolkit, builds a
KubernetesExecutor from a KubernetesConfig, and exposes each async public
method as a tool via get_tools().

Read operations (k8s_list_pods, k8s_get_logs, k8s_describe, k8s_get) carry
no grant requirement.

Mutating operations (k8s_apply_manifest, k8s_scale_deployment,
k8s_delete_resource, k8s_rollout_restart) carry
routing_meta={"requires_grant": True, "grant_scope": "k8s:write"}
for FEAT-211 governance integration.

Note on routing_meta: FEAT-211 (GrantGuard in ToolManager) will gate
mutating tools when wired. Without FEAT-211, mutating tools behave like
any other tool — no gating occurs. This toolkit only MARKS the metadata.

## Classes

- **`KubernetesToolkit(AbstractToolkit)`** — Kubernetes cluster management toolkit.
