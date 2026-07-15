---
type: Wiki Entity
title: ParsedReport
id: class:parrot_tools.security.parsers._types.ParsedReport
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result returned by every catalog-level parser's ``parse()`` method.
---

# ParsedReport

Defined in [`parrot_tools.security.parsers._types`](../summaries/mod:parrot_tools.security.parsers._types.md).

```python
class ParsedReport
```

Result returned by every catalog-level parser's ``parse()`` method.

Attributes:
    severity_summary: Aggregated severity counts for the report.
    top_findings: Up to 10 findings sorted by severity desc, then finding_id asc.
