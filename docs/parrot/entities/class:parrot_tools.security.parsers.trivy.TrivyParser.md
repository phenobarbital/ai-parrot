---
type: Wiki Entity
title: TrivyParser
id: class:parrot_tools.security.parsers.trivy.TrivyParser
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Catalog-level parser for Trivy filesystem/image JSON reports.
---

# TrivyParser

Defined in [`parrot_tools.security.parsers.trivy`](../summaries/mod:parrot_tools.security.parsers.trivy.md).

```python
class TrivyParser
```

Catalog-level parser for Trivy filesystem/image JSON reports.

Accepts Trivy's schema-version-2 JSON (``ArtifactName``, ``Results``
list with ``Vulnerabilities`` entries).

Attributes:
    parser_version: Fixed at ``"1.0.0"`` for v1 of this catalog.

## Methods

- `def parse(self, content: bytes | Path) -> ParsedReport` — Parse Trivy JSON into a ``ParsedReport``.
- `def extract_section(self, content: bytes | Path, section: str) -> dict` — Extract a named section from the Trivy JSON report.
