---
type: Wiki Entity
title: CloudSploitParser
id: class:parrot_tools.security.parsers.cloudsploit.CloudSploitParser
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Catalog-level parser for CloudSploit scan JSON reports.
---

# CloudSploitParser

Defined in [`parrot_tools.security.parsers.cloudsploit`](../summaries/mod:parrot_tools.security.parsers.cloudsploit.md).

```python
class CloudSploitParser
```

Catalog-level parser for CloudSploit scan JSON reports.

Accepts the CloudSploit native JSON format as emitted by its CLI as
well as the ``parrot_tools.cloudsploit.models.ScanResult`` serialized
shape.  Both have a ``findings`` list; the parser normalizes either.

Attributes:
    parser_version: Fixed at ``"1.0.0"`` for v1 of this catalog.

## Methods

- `def parse(self, content: bytes | Path) -> ParsedReport` — Parse CloudSploit JSON into a ``ParsedReport``.
- `def extract_section(self, content: bytes | Path, section: str) -> dict` — Extract a named section from the CloudSploit JSON report.
