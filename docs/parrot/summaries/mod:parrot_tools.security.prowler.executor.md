---
type: Wiki Summary
title: parrot_tools.security.prowler.executor
id: mod:parrot_tools.security.prowler.executor
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Prowler executor for running cloud security scans.
relates_to:
- concept: class:parrot_tools.security.prowler.executor.ProwlerExecutor
  rel: defines
- concept: mod:parrot_tools.security.base_executor
  rel: references
- concept: mod:parrot_tools.security.prowler.config
  rel: references
---

# `parrot_tools.security.prowler.executor`

Prowler executor for running cloud security scans.

Extends BaseExecutor to provide Prowler-specific CLI argument building
and scan execution methods.

## Classes

- **`ProwlerExecutor(BaseExecutor)`** — Executes Prowler security scans via Docker or direct CLI.
