---
type: Wiki Entity
title: ProwlerParser
id: class:parrot_tools.security.parsers.prowler.ProwlerParser
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Catalog-level parser for Prowler JSON-OCSF reports.
---

# ProwlerParser

Defined in [`parrot_tools.security.parsers.prowler`](../summaries/mod:parrot_tools.security.parsers.prowler.md).

```python
class ProwlerParser
```

Catalog-level parser for Prowler JSON-OCSF reports.

Accepts either a JSON array ``[{...}, ...]`` or NDJSON format.

Attributes:
    parser_version: Fixed at ``"1.0.0"`` for v1 of this catalog.

## Methods

- `def parse(self, content: bytes | Path) -> ParsedReport` — Parse Prowler JSON-OCSF output into a ``ParsedReport``.
- `def extract_section(self, content: bytes | Path, section: str) -> dict` — Extract a named section from the Prowler JSON report.
