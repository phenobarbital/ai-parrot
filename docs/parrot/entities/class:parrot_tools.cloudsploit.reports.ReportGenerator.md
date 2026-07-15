---
type: Wiki Entity
title: ReportGenerator
id: class:parrot_tools.cloudsploit.reports.ReportGenerator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generates HTML and PDF reports from CloudSploit scan results.
---

# ReportGenerator

Defined in [`parrot_tools.cloudsploit.reports`](../summaries/mod:parrot_tools.cloudsploit.reports.md).

```python
class ReportGenerator
```

Generates HTML and PDF reports from CloudSploit scan results.

Reports include executive summary, severity breakdown charts,
category breakdown, and detailed findings tables.

## Methods

- `async def generate_html(self, result: ScanResult, output_path: Optional[str]=None, max_findings: int=DEFAULT_MAX_FINDINGS) -> str` — Generate HTML report from scan results.
- `async def generate_pdf(self, result: ScanResult, output_path: str, max_findings: int=DEFAULT_MAX_FINDINGS) -> str` — Generate PDF report from scan results.
- `async def generate_comparison_html(self, comparison: ComparisonReport, output_path: Optional[str]=None) -> str` — Generate HTML comparison report.
- `async def generate_comparison_pdf(self, comparison: ComparisonReport, output_path: str) -> str` — Generate PDF comparison report.
- `async def generate_ecr_html(self, result: EcrCollectionResult, output_path: Optional[str]=None) -> str` — Render an interactive HTML vulnerability report from ECR scan data.
