---
type: Wiki Entity
title: ProwlerParser
id: class:parrot_tools.security.prowler.parser.ProwlerParser
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parser for Prowler JSON-OCSF output.
relates_to:
- concept: class:parrot_tools.security.base_parser.BaseParser
  rel: extends
---

# ProwlerParser

Defined in [`parrot_tools.security.prowler.parser`](../summaries/mod:parrot_tools.security.prowler.parser.md).

```python
class ProwlerParser(BaseParser)
```

Parser for Prowler JSON-OCSF output.

Normalizes Prowler findings into unified SecurityFinding format,
enabling cross-tool aggregation with Trivy and Checkov.

Supported formats:
- JSON array: [{"finding_info": ...}, ...]
- NDJSON: {"finding_info": ...}\n{"finding_info": ...}

## Methods

- `def parse(self, raw_output: str) -> ScanResult` — Parse raw Prowler output into a ScanResult.
- `def normalize_finding(self, raw_finding: dict) -> SecurityFinding` — Convert a Prowler OCSF finding to unified SecurityFinding.
