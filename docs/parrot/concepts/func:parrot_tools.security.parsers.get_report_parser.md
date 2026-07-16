---
type: Concept
title: get_report_parser()
id: func:parrot_tools.security.parsers.get_report_parser
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the parser registered for the given scanner name.
---

# get_report_parser

```python
def get_report_parser(scanner: str) -> ReportParser
```

Return the parser registered for the given scanner name.

Args:
    scanner: One of ``"trivy"``, ``"cloudsploit"``, ``"prowler"``,
        ``"checkov"``, ``"aggregator"``.

Returns:
    A :class:`ReportParser` instance for the requested scanner.

Raises:
    ValueError: If no parser is registered for the given scanner name.
