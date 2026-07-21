---
type: Wiki Entity
title: GenericReportComparator
id: class:parrot_tools.s3.comparator.GenericReportComparator
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Structural diff engine for S3-stored report documents.
---

# GenericReportComparator

Defined in [`parrot_tools.s3.comparator`](../summaries/mod:parrot_tools.s3.comparator.md).

```python
class GenericReportComparator
```

Structural diff engine for S3-stored report documents.

Supports two modes:

- **Generic** (``comparison_mode="generic"``): Walks both dicts recursively
  and tracks keys added, removed, and changed with dotted-path notation.
- **Parser-dispatch** (``comparison_mode="parser_dispatch"``): When
  ``scanner="cloudsploit"``, delegates to ``ScanComparator`` for
  richer, domain-aware comparison. Falls back to generic diff on any
  failure or for unknown scanners.

Args:
    max_changes: Maximum number of change entries to include in the
        ``changes`` list. Larger diffs are truncated and the
        ``truncated`` flag is set to ``True``. Defaults to 50.

## Methods

- `def compare(self, baseline: dict | bytes, current: dict | bytes, *, scanner: str | None=None) -> dict` — Compare two report documents and return a structured diff.
