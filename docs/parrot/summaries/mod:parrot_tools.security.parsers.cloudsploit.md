---
type: Wiki Summary
title: parrot_tools.security.parsers.cloudsploit
id: mod:parrot_tools.security.parsers.cloudsploit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Catalog-level CloudSploit JSON parser.
relates_to:
- concept: class:parrot_tools.security.parsers.cloudsploit.CloudSploitParser
  rel: defines
- concept: mod:parrot.storage.security_reports
  rel: references
- concept: mod:parrot_tools.security.parsers._types
  rel: references
---

# `parrot_tools.security.parsers.cloudsploit`

Catalog-level CloudSploit JSON parser.

Parses CloudSploit's scan JSON output (``findings`` + ``summary``) into the
catalog's ``ParsedReport``. Accepts both the raw CloudSploit JSON format and
the ``parrot_tools.cloudsploit.models.ScanResult`` serialized shape.

## Classes

- **`CloudSploitParser`** — Catalog-level parser for CloudSploit scan JSON reports.
