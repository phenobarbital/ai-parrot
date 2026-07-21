---
type: Wiki Summary
title: parrot_tools.security.parsers.prowler
id: mod:parrot_tools.security.parsers.prowler
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Catalog-level Prowler JSON parser.
relates_to:
- concept: class:parrot_tools.security.parsers.prowler.ProwlerParser
  rel: defines
- concept: mod:parrot.storage.security_reports
  rel: references
- concept: mod:parrot_tools.security.parsers._types
  rel: references
---

# `parrot_tools.security.parsers.prowler`

Catalog-level Prowler JSON parser.

Parses Prowler's JSON-OCSF output (array of finding objects) into the
catalog's ``ParsedReport``.

## Classes

- **`ProwlerParser`** — Catalog-level parser for Prowler JSON-OCSF reports.
