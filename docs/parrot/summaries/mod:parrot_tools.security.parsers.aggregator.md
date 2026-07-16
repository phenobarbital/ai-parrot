---
type: Wiki Summary
title: parrot_tools.security.parsers.aggregator
id: mod:parrot_tools.security.parsers.aggregator
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Catalog-level Aggregator passthrough parser.
relates_to:
- concept: class:parrot_tools.security.parsers.aggregator.AggregatorParser
  rel: defines
- concept: mod:parrot.storage.security_reports
  rel: references
- concept: mod:parrot_tools.security.parsers._types
  rel: references
---

# `parrot_tools.security.parsers.aggregator`

Catalog-level Aggregator passthrough parser.

For ``WEEKLY_SUMMARY`` / ``MONTHLY_SUMMARY`` report kinds, the content IS
already a serialized summary JSON produced by the summarizer.  The aggregator
parser extracts the severity breakdown and executive paragraph directly from
that structure without re-parsing scanner output.

## Classes

- **`AggregatorParser`** — Passthrough parser for weekly / monthly aggregated summary reports.
