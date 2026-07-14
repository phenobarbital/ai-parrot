---
type: Wiki Summary
title: parrot_tools.security.parsers
id: mod:parrot_tools.security.parsers
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Catalog-level scanner parser registry.
relates_to:
- concept: func:parrot_tools.security.parsers.get_report_parser
  rel: defines
- concept: mod:parrot_tools.security
  rel: references
- concept: mod:parrot_tools.security.checkov
  rel: references
- concept: mod:parrot_tools.security.prowler
  rel: references
- concept: mod:parrot_tools.security.trivy
  rel: references
---

# `parrot_tools.security.parsers`

Catalog-level scanner parser registry.

Usage::

    from parrot_tools.security.parsers import get_report_parser, ParsedReport, ReportParser

    parser = get_report_parser("trivy")
    report = parser.parse(b"...trivy json...")
    summary = report.severity_summary
    top10 = report.top_findings

## Functions

- `def get_report_parser(scanner: str) -> ReportParser` — Return the parser registered for the given scanner name.
