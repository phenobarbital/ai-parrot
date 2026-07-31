---
type: Wiki Summary
title: parrot_tools.security.checkov.config
id: mod:parrot_tools.security.checkov.config
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Checkov configuration model.
relates_to:
- concept: class:parrot_tools.security.checkov.config.CheckovConfig
  rel: defines
- concept: mod:parrot_tools.security.base_executor
  rel: references
---

# `parrot_tools.security.checkov.config`

Checkov configuration model.

Defines configuration options for running Checkov IaC security scans including
framework selection, check filters, output format, and external policies.

## Classes

- **`CheckovConfig(BaseExecutorConfig)`** — Configuration for Checkov IaC security scanner.
