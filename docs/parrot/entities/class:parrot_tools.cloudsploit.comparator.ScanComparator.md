---
type: Wiki Entity
title: ScanComparator
id: class:parrot_tools.cloudsploit.comparator.ScanComparator
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Compares two CloudSploit scan results to track security posture changes.
---

# ScanComparator

Defined in [`parrot_tools.cloudsploit.comparator`](../summaries/mod:parrot_tools.cloudsploit.comparator.md).

```python
class ScanComparator
```

Compares two CloudSploit scan results to track security posture changes.

## Methods

- `def compare(self, baseline: ScanResult, current: ScanResult) -> ComparisonReport` — Compare baseline and current scan results.
