---
type: Wiki Summary
title: parrot_tools.pulumi.config
id: mod:parrot_tools.pulumi.config
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pulumi configuration and data models.
relates_to:
- concept: class:parrot_tools.pulumi.config.PulumiApplyInput
  rel: defines
- concept: class:parrot_tools.pulumi.config.PulumiConfig
  rel: defines
- concept: class:parrot_tools.pulumi.config.PulumiDestroyInput
  rel: defines
- concept: class:parrot_tools.pulumi.config.PulumiOperationResult
  rel: defines
- concept: class:parrot_tools.pulumi.config.PulumiPlanInput
  rel: defines
- concept: class:parrot_tools.pulumi.config.PulumiResource
  rel: defines
- concept: class:parrot_tools.pulumi.config.PulumiStatusInput
  rel: defines
- concept: mod:parrot_tools.security.base_executor
  rel: references
---

# `parrot_tools.pulumi.config`

Pulumi configuration and data models.

Defines configuration options for running Pulumi operations including
stack management, state backend, and input/output models for all
Pulumi operations (plan, apply, destroy, status).

## Classes

- **`PulumiConfig(BaseExecutorConfig)`** — Configuration for Pulumi executor.
- **`PulumiPlanInput(BaseModel)`** — Input for pulumi_plan operation.
- **`PulumiApplyInput(BaseModel)`** — Input for pulumi_apply operation.
- **`PulumiDestroyInput(BaseModel)`** — Input for pulumi_destroy operation.
- **`PulumiStatusInput(BaseModel)`** — Input for pulumi_status operation.
- **`PulumiResource(BaseModel)`** — A resource in Pulumi state.
- **`PulumiOperationResult(BaseModel)`** — Result of a Pulumi operation.
