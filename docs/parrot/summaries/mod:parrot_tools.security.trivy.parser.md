---
type: Wiki Summary
title: parrot_tools.security.trivy.parser
id: mod:parrot_tools.security.trivy.parser
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Trivy output parser.
relates_to:
- concept: class:parrot_tools.security.trivy.parser.TrivyParser
  rel: defines
- concept: mod:parrot_tools.security.base_parser
  rel: references
- concept: mod:parrot_tools.security.models
  rel: references
---

# `parrot_tools.security.trivy.parser`

Trivy output parser.

Parses Trivy's JSON output (vulnerabilities, secrets, misconfigurations)
into unified SecurityFinding and ScanResult models.

## Classes

- **`TrivyParser(BaseParser)`** — Parser for Trivy JSON output.
