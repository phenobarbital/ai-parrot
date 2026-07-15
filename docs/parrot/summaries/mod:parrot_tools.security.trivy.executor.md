---
type: Wiki Summary
title: parrot_tools.security.trivy.executor
id: mod:parrot_tools.security.trivy.executor
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Trivy executor for running security scans.
relates_to:
- concept: class:parrot_tools.security.trivy.executor.ImageNotFoundError
  rel: defines
- concept: class:parrot_tools.security.trivy.executor.TrivyExecutor
  rel: defines
- concept: mod:parrot_tools.security.base_executor
  rel: references
- concept: mod:parrot_tools.security.trivy.config
  rel: references
---

# `parrot_tools.security.trivy.executor`

Trivy executor for running security scans.

Extends BaseExecutor to provide Trivy-specific CLI argument building
and helper methods for common scan types.

## Classes

- **`ImageNotFoundError(RuntimeError)`** — Raised when a `trivy image` target is not present on the local Docker daemon.
- **`TrivyExecutor(BaseExecutor)`** — Executes Trivy security scans via Docker or direct CLI.
