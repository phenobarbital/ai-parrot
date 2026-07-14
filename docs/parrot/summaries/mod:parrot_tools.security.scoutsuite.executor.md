---
type: Wiki Summary
title: parrot_tools.security.scoutsuite.executor
id: mod:parrot_tools.security.scoutsuite.executor
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ScoutSuite executor for running cloud security scans.
relates_to:
- concept: class:parrot_tools.security.scoutsuite.executor.ScoutSuiteExecutor
  rel: defines
- concept: mod:parrot_tools.security.base_executor
  rel: references
- concept: mod:parrot_tools.security.scoutsuite.config
  rel: references
---

# `parrot_tools.security.scoutsuite.executor`

ScoutSuite executor for running cloud security scans.

Extends BaseExecutor to provide ScoutSuite-specific CLI argument building
and scan execution methods.

## Classes

- **`ScoutSuiteExecutor(BaseExecutor)`** — Executes ScoutSuite security scans.
