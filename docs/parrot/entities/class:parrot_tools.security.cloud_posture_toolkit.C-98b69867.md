---
type: Wiki Entity
title: CloudPostureToolkit
id: class:parrot_tools.security.cloud_posture_toolkit.CloudPostureToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Cloud Security Posture Management toolkit powered by Prowler.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# CloudPostureToolkit

Defined in [`parrot_tools.security.cloud_posture_toolkit`](../summaries/mod:parrot_tools.security.cloud_posture_toolkit.md).

```python
class CloudPostureToolkit(AbstractToolkit)
```

Cloud Security Posture Management toolkit powered by Prowler.

Runs multi-cloud security assessments, compliance scans, and posture
tracking against AWS, Azure, GCP and Kubernetes.

All public async methods automatically become agent tools.

Example:
    toolkit = CloudPostureToolkit()
    result = await toolkit.prowler_run_scan(provider="aws", services=["s3", "iam"])
    findings = await toolkit.prowler_get_findings(severity="CRITICAL")

## Methods

- `async def prowler_run_scan(self, provider: str='aws', services: Optional[list[str]]=None, checks: Optional[list[str]]=None, regions: Optional[list[str]]=None, severity: Optional[list[str]]=None, exclude_passing: bool=False) -> ScanResult` — Run a Prowler security scan against cloud infrastructure.
- `async def prowler_compliance_scan(self, framework: str, provider: str='aws', regions: Optional[list[str]]=None, exclude_passing: bool=True) -> ScanResult` — Run a compliance-focused security scan.
- `async def prowler_scan_service(self, service: str, provider: str='aws', regions: Optional[list[str]]=None, exclude_passing: bool=False) -> ScanResult` — Scan a specific cloud service.
- `async def prowler_list_checks(self, provider: str='aws', service: Optional[str]=None) -> list[dict]` — List available Prowler security checks.
- `async def prowler_list_services(self, provider: str='aws') -> list[str]` — List scannable services for a cloud provider.
- `async def prowler_get_summary(self) -> dict` — Get summary statistics from the last scan.
- `async def prowler_get_findings(self, severity: Optional[str]=None, service: Optional[str]=None, status: Optional[str]=None, limit: Optional[int]=None) -> list[SecurityFinding]` — Get findings from the last scan with optional filters.
- `async def prowler_generate_report(self, output_path: str, format: str='html') -> str` — Generate a report from the last scan results.
- `async def prowler_compare_scans(self, baseline_path: str) -> ComparisonDelta` — Compare current scan results against a baseline.
