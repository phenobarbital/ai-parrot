---
type: Wiki Entity
title: BaseParser
id: class:parrot_tools.security.base_parser.BaseParser
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract parser for security scanner output.
---

# BaseParser

Defined in [`parrot_tools.security.base_parser`](../summaries/mod:parrot_tools.security.base_parser.md).

```python
class BaseParser(ABC)
```

Abstract parser for security scanner output.

Each scanner (Prowler, Trivy, Checkov) implements its own parser
that normalizes raw output into the unified ScanResult format.

Subclasses must implement:
- parse(): Parse raw scanner stdout into a normalized ScanResult
- normalize_finding(): Convert a single raw finding into SecurityFinding

## Methods

- `def parse(self, raw_output: str) -> ScanResult` — Parse raw scanner stdout into a normalized ScanResult.
- `def normalize_finding(self, raw_finding: dict) -> SecurityFinding` — Convert a single raw finding into a unified SecurityFinding.
- `def save_result(self, result: ScanResult, path: str) -> str` — Persist scan result to a JSON file.
- `def load_result(self, path: str) -> ScanResult` — Load a previously saved scan result from JSON file.
