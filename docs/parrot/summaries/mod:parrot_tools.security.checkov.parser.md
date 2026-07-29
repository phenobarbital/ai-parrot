---
type: Wiki Summary
title: parrot_tools.security.checkov.parser
id: mod:parrot_tools.security.checkov.parser
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Checkov output parser.
relates_to:
- concept: class:parrot_tools.security.checkov.parser.CheckovParser
  rel: defines
- concept: mod:parrot_tools.security.base_parser
  rel: references
- concept: mod:parrot_tools.security.models
  rel: references
---

# `parrot_tools.security.checkov.parser`

Checkov output parser.

Parses Checkov's JSON output (IaC misconfigurations) into unified
SecurityFinding and ScanResult models.

## Classes

- **`CheckovParser(BaseParser)`** — Parser for Checkov JSON output.
