---
type: Wiki Entity
title: TrivyExecutor
id: class:parrot_tools.security.trivy.executor.TrivyExecutor
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Executes Trivy security scans via Docker or direct CLI.
relates_to:
- concept: class:parrot_tools.security.base_executor.BaseExecutor
  rel: extends
---

# TrivyExecutor

Defined in [`parrot_tools.security.trivy.executor`](../summaries/mod:parrot_tools.security.trivy.executor.md).

```python
class TrivyExecutor(BaseExecutor)
```

Executes Trivy security scans via Docker or direct CLI.

Trivy CLI pattern: `trivy <scan_type> [options] <target>`

Scan types:
- image: Container image vulnerability scanning
- fs: Filesystem vulnerability and secret scanning
- repo: Git repository scanning
- config: IaC misconfiguration detection
- k8s: Kubernetes cluster scanning
- sbom: Software Bill of Materials generation

Example:
    config = TrivyConfig(severity_filter=["CRITICAL", "HIGH"])
    executor = TrivyExecutor(config)
    stdout, stderr, code = await executor.scan_image("nginx:latest")

## Methods

- `async def scan_image(self, image: str, severity: Optional[list[str]]=None, ignore_unfixed: Optional[bool]=None, scanners: Optional[list[str]]=None) -> tuple[str, str, int]` — Scan a container image for vulnerabilities.
- `async def scan_filesystem(self, path: str, severity: Optional[list[str]]=None, scanners: Optional[list[str]]=None) -> tuple[str, str, int]` — Scan a filesystem directory for vulnerabilities and secrets.
- `async def scan_repository(self, repo_url: str, branch: Optional[str]=None, severity: Optional[list[str]]=None) -> tuple[str, str, int]` — Scan a Git repository for vulnerabilities.
- `async def scan_config(self, path: str, compliance: Optional[str]=None, policy_dir: Optional[str]=None) -> tuple[str, str, int]` — Scan IaC configuration files for misconfigurations.
- `async def scan_k8s(self, context: Optional[str]=None, namespace: Optional[str]=None, compliance: Optional[str]=None, components: Optional[list[str]]=None) -> tuple[str, str, int]` — Scan a Kubernetes cluster for vulnerabilities and misconfigurations.
- `async def generate_sbom(self, target: str, scan_type: str='image', sbom_format: str='cyclonedx', output_file: Optional[str]=None) -> tuple[str, str, int]` — Generate a Software Bill of Materials (SBOM) for a target.
- `async def list_scanners(self) -> tuple[str, str, int]` — List available scanner types.
