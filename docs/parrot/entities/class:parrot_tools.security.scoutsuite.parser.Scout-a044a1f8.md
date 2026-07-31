---
type: Wiki Entity
title: ScoutSuiteParser
id: class:parrot_tools.security.scoutsuite.parser.ScoutSuiteParser
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parses ScoutSuite JSON output into unified SecurityFinding models.
relates_to:
- concept: class:parrot_tools.security.base_parser.BaseParser
  rel: extends
---

# ScoutSuiteParser

Defined in [`parrot_tools.security.scoutsuite.parser`](../summaries/mod:parrot_tools.security.scoutsuite.parser.md).

```python
class ScoutSuiteParser(BaseParser)
```

Parses ScoutSuite JSON output into unified SecurityFinding models.

## Methods

- `def normalize_finding(self, raw_finding: dict) -> SecurityFinding` — Convert a single raw ScoutSuite finding into a SecurityFinding.
- `def parse(self, output: str) -> ScanResult` — Parse ScoutSuite JSON output string.
- `def parse_dict(self, data: dict[str, Any]) -> ScanResult` — Parse loaded ScoutSuite JSON dictionary.
