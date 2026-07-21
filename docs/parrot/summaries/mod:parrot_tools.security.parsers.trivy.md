---
type: Wiki Summary
title: parrot_tools.security.parsers.trivy
id: mod:parrot_tools.security.parsers.trivy
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Catalog-level Trivy JSON parser.
relates_to:
- concept: class:parrot_tools.security.parsers.trivy.TrivyParser
  rel: defines
- concept: mod:parrot.storage.security_reports
  rel: references
- concept: mod:parrot_tools.security.parsers._types
  rel: references
---

# `parrot_tools.security.parsers.trivy`

Catalog-level Trivy JSON parser.

Parses Trivy's schema-version-2 JSON output into the catalog's
``ParsedReport`` (``SeverityBreakdown`` + ``EmbeddedFinding``).

## Classes

- **`TrivyParser`** — Catalog-level parser for Trivy filesystem/image JSON reports.
