---
type: Wiki Entity
title: CheckovParser
id: class:parrot_tools.security.parsers.checkov.CheckovParser
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Catalog-level parser for Checkov JSON reports.
---

# CheckovParser

Defined in [`parrot_tools.security.parsers.checkov`](../summaries/mod:parrot_tools.security.parsers.checkov.md).

```python
class CheckovParser
```

Catalog-level parser for Checkov JSON reports.

Accepts both single-check-type ``{check_type, results, ...}`` and a
list of per-check-type objects (Checkov can produce either).

Attributes:
    parser_version: Fixed at ``"1.0.0"`` for v1 of this catalog.

## Methods

- `def parse(self, content: bytes | Path) -> ParsedReport` — Parse Checkov JSON into a ``ParsedReport``.
- `def extract_section(self, content: bytes | Path, section: str) -> dict` — Extract a named section from the Checkov JSON report.
