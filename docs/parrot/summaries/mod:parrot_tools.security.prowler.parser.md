---
type: Wiki Summary
title: parrot_tools.security.prowler.parser
id: mod:parrot_tools.security.prowler.parser
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Prowler output parser.
relates_to:
- concept: class:parrot_tools.security.prowler.parser.ProwlerParser
  rel: defines
- concept: mod:parrot_tools.security.base_parser
  rel: references
- concept: mod:parrot_tools.security.models
  rel: references
---

# `parrot_tools.security.prowler.parser`

Prowler output parser.

Parses Prowler's JSON-OCSF output into unified SecurityFinding and ScanResult models.
Supports both JSON array and newline-delimited JSON (NDJSON) formats.

## Classes

- **`ProwlerParser(BaseParser)`** — Parser for Prowler JSON-OCSF output.
