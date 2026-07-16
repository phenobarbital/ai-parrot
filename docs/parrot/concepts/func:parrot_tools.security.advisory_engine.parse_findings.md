---
type: Concept
title: parse_findings()
id: func:parrot_tools.security.advisory_engine.parse_findings
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Try to parse ``content`` into a list of SecurityFinding objects.
---

# parse_findings

```python
def parse_findings(ref: ReportRef, content: bytes) -> list[SecurityFinding]
```

Try to parse ``content`` into a list of SecurityFinding objects.

The catalog-level parsers return ``ParsedReport`` with ``EmbeddedFinding``
objects, not the richer ``SecurityFinding`` shape required by
``ComplianceMapper``.  We therefore call ``extract_section("full")``
(returning raw scanner JSON) and reconstruct ``SecurityFinding`` objects.

Degrades gracefully: if parsing fails or the scanner is unrecognised,
returns an empty list so the caller falls back to severity-summary deltas.

Args:
    ref: Report metadata (provides scanner name and framework).
    content: Raw scanner output bytes.

Returns:
    Possibly-empty list of SecurityFinding objects.
