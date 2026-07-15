---
type: Wiki Summary
title: parrot_tools.security.parsers.checkov
id: mod:parrot_tools.security.parsers.checkov
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Catalog-level Checkov JSON parser.
relates_to:
- concept: class:parrot_tools.security.parsers.checkov.CheckovParser
  rel: defines
- concept: mod:parrot.storage.security_reports
  rel: references
- concept: mod:parrot_tools.security.parsers._types
  rel: references
---

# `parrot_tools.security.parsers.checkov`

Catalog-level Checkov JSON parser.

Parses Checkov's ``check_type`` / ``results`` JSON format into the catalog's
``ParsedReport``.

## Classes

- **`CheckovParser`** — Catalog-level parser for Checkov JSON reports.
