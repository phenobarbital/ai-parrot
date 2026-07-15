---
type: Wiki Entity
title: CloudSploitToolkit
id: class:parrot_tools.cloudsploit.toolkit.CloudSploitToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Cloud Security Posture Management toolkit powered by CloudSploit.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
- concept: class:parrot_tools.security.persistence.ReportPersistenceMixin
  rel: extends
---

# CloudSploitToolkit

Defined in [`parrot_tools.cloudsploit.toolkit`](../summaries/mod:parrot_tools.cloudsploit.toolkit.md).

```python
class CloudSploitToolkit(ReportPersistenceMixin, AbstractToolkit)
```

Cloud Security Posture Management toolkit powered by CloudSploit.

Runs security scans against AWS infrastructure, parses results,
generates reports, and tracks security posture over time.

## Methods

- `async def run_scan(self, plugins: Optional[list[str]]=None, ignore_ok: bool=False, suppress: Optional[list[str]]=None, config: Optional[str]=None) -> ScanResult` — Run a CloudSploit security scan against cloud infrastructure.
- `async def run_compliance_scan(self, framework: str, ignore_ok: bool=True, config: Optional[str]=None) -> ScanResult` — Run a compliance-filtered CloudSploit scan.
- `async def scan_open_ports(self, provider: str='aws', extra_plugins: Optional[list[str]]=None, ignore_ok: bool=False, suppress: Optional[list[str]]=None, config: Optional[str]=None) -> ScanResult` — Scan only the "open ports" plugins for a given cloud provider.
- `async def scan_security_groups(self, extra_plugins: Optional[list[str]]=None, ignore_ok: bool=False, suppress: Optional[list[str]]=None, config: Optional[str]=None) -> ScanResult` — Scan AWS EC2 Security Groups for open-port misconfigurations.
- `async def scan_firewall_rules(self, extra_plugins: Optional[list[str]]=None, ignore_ok: bool=False, suppress: Optional[list[str]]=None, config: Optional[str]=None) -> ScanResult` — Scan GCP Firewall Rules for open-port misconfigurations.
- `async def scan_security_lists(self, extra_plugins: Optional[list[str]]=None, ignore_ok: bool=False, suppress: Optional[list[str]]=None, config: Optional[str]=None) -> ScanResult` — Scan OCI Security Lists for open-port misconfigurations.
- `async def get_summary(self) -> dict` — Get a summary of the most recent scan results.
- `async def generate_report(self, format: str='html', output_path: Optional[str]=None) -> str` — Generate a security report from the most recent scan.
- `async def compare_scans(self, baseline_path: str, current_path: Optional[str]=None) -> ComparisonReport` — Compare two scan results to track security posture changes.
- `async def list_findings(self, severity: Optional[str]=None, category: Optional[str]=None, region: Optional[str]=None) -> list[dict]` — List findings from the most recent scan with optional filters.
- `async def collect_ecr_findings(self, repos: Optional[list[EcrRepoPlan]]=None, region: Optional[str]=None, aws_id: Optional[str]=None, concurrency: Optional[int]=None, plan: Optional[str]=None) -> EcrCollectionResult` — Aggregate ECR vulnerability scan findings across many repos.
- `async def generate_ecr_report(self, output_path: Optional[str]=None, result: Optional[EcrCollectionResult]=None) -> str` — Render the interactive HTML ECR vulnerability report.
