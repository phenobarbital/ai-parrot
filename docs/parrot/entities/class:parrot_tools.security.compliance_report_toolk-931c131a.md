---
type: Wiki Entity
title: ComplianceReportToolkit
id: class:parrot_tools.security.compliance_report_toolkit.ComplianceReportToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Multi-scanner compliance reporting toolkit.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
- concept: class:parrot_tools.security.persistence.ReportPersistenceMixin
  rel: extends
---

# ComplianceReportToolkit

Defined in [`parrot_tools.security.compliance_report_toolkit`](../summaries/mod:parrot_tools.security.compliance_report_toolkit.md).

```python
class ComplianceReportToolkit(ReportPersistenceMixin, AbstractToolkit)
```

Multi-scanner compliance reporting toolkit.

Orchestrates Prowler, Trivy, and Checkov to produce unified compliance
reports. Runs scans in parallel and handles partial failures gracefully.

All public async methods automatically become agent tools.

Example:
    toolkit = ComplianceReportToolkit()
    report = await toolkit.compliance_full_scan(
        provider="aws",
        target_image="nginx:latest",
        iac_path="/terraform"
    )
    path = await toolkit.compliance_soc2_report()

## Methods

- `async def compliance_full_scan(self, provider: str='aws', target_image: Optional[str]=None, iac_path: Optional[str]=None, k8s_context: Optional[str]=None, framework: Optional[str]=None, regions: Optional[list[str]]=None, progress_callback: Callable[[str], None] | None=None) -> ConsolidatedReport` — Run comprehensive security scan across all configured scanners.
- `async def compliance_soc2_report(self, provider: str='aws', output_path: Optional[str]=None, include_evidence: bool=True) -> str` — Generate SOC2 compliance report.
- `async def compliance_hipaa_report(self, provider: str='aws', output_path: Optional[str]=None, include_evidence: bool=True) -> str` — Generate HIPAA compliance report.
- `async def compliance_pci_report(self, provider: str='aws', output_path: Optional[str]=None, include_evidence: bool=True) -> str` — Generate PCI-DSS compliance report.
- `async def compliance_custom_report(self, framework: str, provider: str='aws', output_path: Optional[str]=None, include_evidence: bool=True) -> str` — Generate compliance report for any supported framework.
- `async def compliance_executive_summary(self, provider: str='aws') -> dict` — Generate executive summary of security posture.
- `async def compliance_get_gaps(self, framework: str='soc2', provider: str='aws') -> list[dict]` — Get compliance gaps for a specific framework.
- `async def compliance_get_remediation_plan(self, max_items: int=20, provider: str='aws') -> list[dict]` — Get prioritized remediation plan.
- `async def compliance_compare_reports(self, baseline_index: int=-2, current_index: int=-1) -> ComparisonDelta` — Compare two scan reports to detect drift.
- `async def compliance_export_findings(self, output_path: str, format: str='csv', provider: str='aws') -> str` — Export findings to CSV or JSON format.
