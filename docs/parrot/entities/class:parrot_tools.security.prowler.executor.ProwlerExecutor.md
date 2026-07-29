---
type: Wiki Entity
title: ProwlerExecutor
id: class:parrot_tools.security.prowler.executor.ProwlerExecutor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Executes Prowler security scans via Docker or direct CLI.
relates_to:
- concept: class:parrot_tools.security.base_executor.BaseExecutor
  rel: extends
---

# ProwlerExecutor

Defined in [`parrot_tools.security.prowler.executor`](../summaries/mod:parrot_tools.security.prowler.executor.md).

```python
class ProwlerExecutor(BaseExecutor)
```

Executes Prowler security scans via Docker or direct CLI.

Prowler CLI pattern: `prowler <provider> [options]`

Supports:
- AWS, Azure, GCP, Kubernetes providers
- Multiple output formats
- Region/service filtering
- Compliance framework filtering
- Check exclusions

## Methods

- `async def run_scan(self, provider: Optional[str]=None, services: Optional[list[str]]=None, checks: Optional[list[str]]=None, compliance_framework: Optional[str]=None, severity: Optional[list[str]]=None, filter_regions: Optional[list[str]]=None) -> tuple[str, str, int]` — Run a Prowler security scan.
- `async def run_scan_streaming(self, progress_callback=None, provider: Optional[str]=None, services: Optional[list[str]]=None, checks: Optional[list[str]]=None, compliance_framework: Optional[str]=None, severity: Optional[list[str]]=None, filter_regions: Optional[list[str]]=None) -> tuple[str, str, int]` — Run a Prowler scan with real-time stderr streaming.
- `async def list_checks(self, provider: Optional[str]=None, service: Optional[str]=None) -> tuple[str, str, int]` — List available Prowler checks.
- `async def list_services(self, provider: Optional[str]=None) -> tuple[str, str, int]` — List available services for a provider.
- `async def list_compliance_frameworks(self, provider: Optional[str]=None) -> tuple[str, str, int]` — List available compliance frameworks.
