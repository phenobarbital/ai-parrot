---
type: Wiki Summary
title: parrot_tools.kubernetes.config
id: mod:parrot_tools.kubernetes.config
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Kubernetes Toolkit configuration and result models.
relates_to:
- concept: class:parrot_tools.kubernetes.config.K8sOperationResult
  rel: defines
- concept: class:parrot_tools.kubernetes.config.KubernetesConfig
  rel: defines
---

# `parrot_tools.kubernetes.config`

Kubernetes Toolkit configuration and result models.

Provides Pydantic models for KubernetesConfig and K8sOperationResult,
mirroring the PulumiConfig/PulumiOperationResult pattern.

## Classes

- **`KubernetesConfig(BaseModel)`** — Configuration for KubernetesExecutor.
- **`K8sOperationResult(BaseModel)`** — Result of a Kubernetes operation.
