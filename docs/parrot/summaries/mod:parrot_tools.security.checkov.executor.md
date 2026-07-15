---
type: Wiki Summary
title: parrot_tools.security.checkov.executor
id: mod:parrot_tools.security.checkov.executor
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Checkov executor for running IaC security scans.
relates_to:
- concept: class:parrot_tools.security.checkov.executor.CheckovExecutor
  rel: defines
- concept: mod:parrot_tools.security.base_executor
  rel: references
- concept: mod:parrot_tools.security.checkov.config
  rel: references
---

# `parrot_tools.security.checkov.executor`

Checkov executor for running IaC security scans.

Extends BaseExecutor to provide Checkov-specific CLI argument building
and helper methods for common scan types.

## Classes

- **`CheckovExecutor(BaseExecutor)`** — Executes Checkov IaC security scans via Docker or direct CLI.
