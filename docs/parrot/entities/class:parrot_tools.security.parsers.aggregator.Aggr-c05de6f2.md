---
type: Wiki Entity
title: AggregatorParser
id: class:parrot_tools.security.parsers.aggregator.AggregatorParser
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Passthrough parser for weekly / monthly aggregated summary reports.
---

# AggregatorParser

Defined in [`parrot_tools.security.parsers.aggregator`](../summaries/mod:parrot_tools.security.parsers.aggregator.md).

```python
class AggregatorParser
```

Passthrough parser for weekly / monthly aggregated summary reports.

The expected JSON shape mirrors the output of ``WeeklySummarizer`` /
``MonthlySummarizer``:

.. code-block:: json

    {
      "severity_summary": {"critical": 2, "high": 5, ...},
      "top_findings": [
        {"finding_id": "...", "severity": "CRITICAL", "title": "...", ...}
      ],
      "executive_paragraph": "Overall posture improved this week..."
    }

Attributes:
    parser_version: Fixed at ``"1.0.0"`` for v1 of this catalog.

## Methods

- `def parse(self, content: bytes | Path) -> ParsedReport` — Parse an aggregated summary JSON into a ``ParsedReport``.
- `def extract_section(self, content: bytes | Path, section: str) -> dict` — Extract a named section from the aggregated summary JSON.
