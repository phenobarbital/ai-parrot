---
type: Wiki Summary
title: parrot_tools.security.trivy.config
id: mod:parrot_tools.security.trivy.config
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Trivy configuration model.
relates_to:
- concept: class:parrot_tools.security.trivy.config.TrivyConfig
  rel: defines
- concept: mod:parrot_tools.security.base_executor
  rel: references
---

# `parrot_tools.security.trivy.config`

Trivy configuration model.

Defines configuration options for running Trivy security scans including
severity filters, scanner types, output formats, and cache settings.

## Classes

- **`TrivyConfig(BaseExecutorConfig)`** — Configuration for Trivy security scanner.
