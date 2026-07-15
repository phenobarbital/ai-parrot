---
type: Wiki Entity
title: ReportGenerator
id: class:parrot_tools.security.reports.generator.ReportGenerator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Multi-format report generator with Jinja2 templates.
---

# ReportGenerator

Defined in [`parrot_tools.security.reports.generator`](../summaries/mod:parrot_tools.security.reports.generator.md).

```python
class ReportGenerator
```

Multi-format report generator with Jinja2 templates.

Generates compliance reports (SOC2, HIPAA, PCI-DSS), executive summaries,
and consolidated multi-scanner reports from security scan results.

Example:
    generator = ReportGenerator(output_dir="/tmp/reports")
    path = await generator.generate_compliance_report(
        consolidated_report,
        ComplianceFramework.SOC2
    )

## Methods

- `async def generate_compliance_report(self, consolidated: ConsolidatedReport, framework: ComplianceFramework, format: str='html', output_path: Optional[str]=None, include_evidence: bool=True) -> str` — Generate a compliance report for a specific framework.
- `async def generate_executive_summary(self, consolidated: ConsolidatedReport, format: str='html', output_path: Optional[str]=None) -> str` — Generate an executive summary report.
- `async def generate_consolidated_report(self, consolidated: ConsolidatedReport, format: str='html', output_path: Optional[str]=None, include_all_findings: bool=False) -> str` — Generate a full consolidated report from all scanners.
- `async def export_findings_csv(self, findings: list[SecurityFinding], output_path: str) -> str` — Export findings to CSV format.
- `async def generate_report_from_scan_result(self, scan_result: ScanResult, report_type: str='consolidated', output_path: Optional[str]=None) -> str` — Generate a report from a single scan result.
