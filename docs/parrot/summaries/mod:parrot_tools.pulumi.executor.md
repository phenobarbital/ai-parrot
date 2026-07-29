---
type: Wiki Summary
title: parrot_tools.pulumi.executor
id: mod:parrot_tools.pulumi.executor
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pulumi executor for running infrastructure deployment commands.
relates_to:
- concept: class:parrot_tools.pulumi.executor.PulumiExecutor
  rel: defines
- concept: mod:parrot_tools.pulumi.config
  rel: references
- concept: mod:parrot_tools.security.base_executor
  rel: references
---

# `parrot_tools.pulumi.executor`

Pulumi executor for running infrastructure deployment commands.

Extends BaseExecutor to provide Pulumi-specific CLI argument building
and helper methods for preview, apply, destroy, and status operations.

## Classes

- **`PulumiExecutor(BaseExecutor)`** — Executes Pulumi CLI commands via Docker or direct CLI.
