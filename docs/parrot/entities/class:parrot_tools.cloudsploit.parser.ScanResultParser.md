---
type: Wiki Entity
title: ScanResultParser
id: class:parrot_tools.cloudsploit.parser.ScanResultParser
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parses CloudSploit JSON output into typed ScanResult objects.
---

# ScanResultParser

Defined in [`parrot_tools.cloudsploit.parser`](../summaries/mod:parrot_tools.cloudsploit.parser.md).

```python
class ScanResultParser
```

Parses CloudSploit JSON output into typed ScanResult objects.

## Methods

- `def parse(self, raw_json: str, timestamp: Optional[datetime]=None) -> ScanResult` — Parse raw CloudSploit JSON string into ScanResult.
- `def filter_by_severity(self, result: ScanResult, levels: list[SeverityLevel]) -> ScanResult` — Return a new ScanResult containing only findings with the given severity levels.
- `def filter_by_category(self, result: ScanResult, categories: list[str]) -> ScanResult` — Return a new ScanResult containing only findings in the given categories.
- `def filter_by_region(self, result: ScanResult, regions: list[str]) -> ScanResult` — Return a new ScanResult containing only findings in the given regions.
- `def save_result(self, result: ScanResult, path: str) -> str` — Save ScanResult as JSON to filesystem.
- `def load_result(self, path: str) -> ScanResult` — Load a ScanResult from a previously saved JSON file.
