---
type: Wiki Summary
title: parrot_tools.security.base_parser
id: mod:parrot_tools.security.base_parser
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base parser for normalizing security scanner output.
relates_to:
- concept: class:parrot_tools.security.base_parser.BaseParser
  rel: defines
- concept: mod:parrot_tools.security.models
  rel: references
---

# `parrot_tools.security.base_parser`

Base parser for normalizing security scanner output.

Provides an abstract interface for parsing scanner-specific output
into the unified SecurityFinding and ScanResult models.

## Classes

- **`BaseParser(ABC)`** — Abstract parser for security scanner output.
