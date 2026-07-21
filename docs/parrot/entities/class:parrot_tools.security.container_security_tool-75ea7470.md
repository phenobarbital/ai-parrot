---
type: Wiki Entity
title: ContainerSecurityToolkit
id: class:parrot_tools.security.container_security_toolkit.ContainerSecurityToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Container and infrastructure security toolkit powered by Trivy.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
- concept: class:parrot_tools.security.persistence.ReportPersistenceMixin
  rel: extends
---

# ContainerSecurityToolkit

Defined in [`parrot_tools.security.container_security_toolkit`](../summaries/mod:parrot_tools.security.container_security_toolkit.md).

```python
class ContainerSecurityToolkit(ReportPersistenceMixin, AbstractToolkit)
```

Container and infrastructure security toolkit powered by Trivy.

Scans container images, filesystems, git repositories, Kubernetes clusters,
and Infrastructure as Code for vulnerabilities, secrets, and misconfigurations.

All public async methods automatically become agent tools.

Example:
    toolkit = ContainerSecurityToolkit()
    result = await toolkit.trivy_scan_image(image="nginx:latest")
    findings = await toolkit.trivy_get_findings(severity="CRITICAL")

## Methods

- `async def trivy_scan_image(self, image: str, severity: Optional[list[str]]=None, ignore_unfixed: bool=False, scanners: Optional[list[str]]=None) -> ScanResult` — Scan a container image for vulnerabilities, secrets, and misconfigurations.
- `async def trivy_scan_filesystem(self, path: str, severity: Optional[list[str]]=None, scanners: Optional[list[str]]=None) -> ScanResult` — Scan a local filesystem directory for vulnerabilities and secrets.
- `async def trivy_scan_repo(self, repo_url: str, branch: Optional[str]=None, severity: Optional[list[str]]=None) -> ScanResult` — Scan a Git repository for vulnerabilities.
- `async def trivy_scan_k8s(self, context: Optional[str]=None, namespace: Optional[str]=None, compliance: Optional[str]=None, components: Optional[list[str]]=None) -> ScanResult` — Scan a Kubernetes cluster for vulnerabilities and misconfigurations.
- `async def trivy_scan_iac(self, path: str, compliance: Optional[str]=None, config_type: Optional[str]=None) -> ScanResult` — Scan Infrastructure as Code configurations for misconfigurations.
- `async def trivy_generate_sbom(self, target: str, format: str='cyclonedx', output_path: Optional[str]=None, scan_type: str='image') -> str` — Generate a Software Bill of Materials (SBOM) for a target.
- `async def trivy_get_summary(self) -> dict` — Get summary statistics from the last scan.
- `async def trivy_get_findings(self, severity: Optional[str]=None, scanner_type: Optional[str]=None, limit: Optional[int]=None) -> list[SecurityFinding]` — Get findings from the last scan with optional filters.
- `async def trivy_generate_report(self, output_path: str, format: str='html') -> str` — Generate a report from the last scan results.
- `async def trivy_compare_scans(self, baseline_path: str) -> ComparisonDelta` — Compare current scan results against a baseline.
