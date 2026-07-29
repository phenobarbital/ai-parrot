---
type: Wiki Entity
title: SecretsIaCToolkit
id: class:parrot_tools.security.secrets_iac_toolkit.SecretsIaCToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Infrastructure as Code and Secrets scanning toolkit powered by Checkov.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# SecretsIaCToolkit

Defined in [`parrot_tools.security.secrets_iac_toolkit`](../summaries/mod:parrot_tools.security.secrets_iac_toolkit.md).

```python
class SecretsIaCToolkit(AbstractToolkit)
```

Infrastructure as Code and Secrets scanning toolkit powered by Checkov.

Scans Terraform, CloudFormation, Kubernetes, Helm, Dockerfiles, GitHub Actions,
and code for security misconfigurations and exposed secrets.

All public async methods automatically become agent tools.

Example:
    toolkit = SecretsIaCToolkit()
    result = await toolkit.checkov_scan_terraform(path="./terraform")
    findings = await toolkit.checkov_get_findings(severity="CRITICAL")

## Methods

- `async def checkov_scan_directory(self, path: str, frameworks: Optional[list[str]]=None, checks: Optional[list[str]]=None, skip_checks: Optional[list[str]]=None) -> ScanResult` — Scan an IaC directory for security misconfigurations.
- `async def checkov_scan_file(self, file_path: str, framework: Optional[str]=None, checks: Optional[list[str]]=None, skip_checks: Optional[list[str]]=None) -> ScanResult` — Scan a single IaC file for security misconfigurations.
- `async def checkov_scan_terraform(self, path: str, var_files: Optional[list[str]]=None, checks: Optional[list[str]]=None, skip_checks: Optional[list[str]]=None, download_modules: bool=True) -> ScanResult` — Scan Terraform configurations for security misconfigurations.
- `async def checkov_scan_cloudformation(self, path: str, template_file: Optional[str]=None, checks: Optional[list[str]]=None, skip_checks: Optional[list[str]]=None) -> ScanResult` — Scan CloudFormation templates for security misconfigurations.
- `async def checkov_scan_kubernetes(self, path: str, namespace_filter: Optional[str]=None, checks: Optional[list[str]]=None, skip_checks: Optional[list[str]]=None) -> ScanResult` — Scan Kubernetes manifests for security misconfigurations.
- `async def checkov_scan_dockerfile(self, path: str, checks: Optional[list[str]]=None, skip_checks: Optional[list[str]]=None) -> ScanResult` — Scan Dockerfiles for security misconfigurations.
- `async def checkov_scan_helm(self, path: str, values_file: Optional[str]=None, checks: Optional[list[str]]=None, skip_checks: Optional[list[str]]=None) -> ScanResult` — Scan Helm charts for security misconfigurations.
- `async def checkov_scan_secrets(self, path: str, skip_paths: Optional[list[str]]=None) -> ScanResult` — Scan code for exposed secrets using entropy-based detection.
- `async def checkov_scan_github_actions(self, path: str, checks: Optional[list[str]]=None, skip_checks: Optional[list[str]]=None) -> ScanResult` — Scan GitHub Actions workflows for security misconfigurations.
- `async def checkov_list_checks(self, framework: Optional[str]=None) -> list[dict]` — List available Checkov checks.
- `async def checkov_get_summary(self) -> dict` — Get summary statistics from the last scan.
- `async def checkov_get_findings(self, severity: Optional[str]=None, framework: Optional[str]=None, limit: Optional[int]=None) -> list[SecurityFinding]` — Get findings from the last scan with optional filters.
- `async def checkov_generate_report(self, output_path: str, format: str='json') -> str` — Generate a report from the last scan results.
- `async def checkov_compare_scans(self, baseline_path: str, current_path: Optional[str]=None) -> ComparisonDelta` — Compare current scan results against a baseline.
