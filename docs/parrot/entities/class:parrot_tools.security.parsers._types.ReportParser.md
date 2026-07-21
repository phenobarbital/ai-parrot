---
type: Wiki Entity
title: ReportParser
id: class:parrot_tools.security.parsers._types.ReportParser
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Protocol every catalog-level parser must satisfy.
---

# ReportParser

Defined in [`parrot_tools.security.parsers._types`](../summaries/mod:parrot_tools.security.parsers._types.md).

```python
class ReportParser(Protocol)
```

Protocol every catalog-level parser must satisfy.

Attributes:
    parser_version: Semantic version string used to populate
        ``ReportRef.parser_version`` (e.g., ``"1.0.0"``).

## Methods

- `def parse(self, content: bytes | Path) -> ParsedReport` — Parse scanner output into a canonical ``ParsedReport``.
- `def extract_section(self, content: bytes | Path, section: str) -> dict` — Extract a named section from the scanner output.
