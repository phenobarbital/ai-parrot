---
type: Wiki Entity
title: CheckovExecutor
id: class:parrot_tools.security.checkov.executor.CheckovExecutor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Executes Checkov IaC security scans via Docker or direct CLI.
relates_to:
- concept: class:parrot_tools.security.base_executor.BaseExecutor
  rel: extends
---

# CheckovExecutor

Defined in [`parrot_tools.security.checkov.executor`](../summaries/mod:parrot_tools.security.checkov.executor.md).

```python
class CheckovExecutor(BaseExecutor)
```

Executes Checkov IaC security scans via Docker or direct CLI.

Checkov CLI pattern: `checkov -d <dir> | -f <file> [options]`

Supported frameworks:
- terraform: Terraform configurations
- cloudformation: AWS CloudFormation templates
- kubernetes: Kubernetes manifests and Helm charts
- dockerfile: Dockerfile security checks
- arm: Azure Resource Manager templates
- bicep: Azure Bicep configurations
- serverless: Serverless Framework configurations
- github_actions: GitHub Actions workflows
- And many more...

Example:
    config = CheckovConfig(frameworks=["terraform"])
    executor = CheckovExecutor(config)
    stdout, stderr, code = await executor.scan_directory("./terraform")

## Methods

- `async def scan_directory(self, path: str, frameworks: Optional[list[str]]=None, run_checks: Optional[list[str]]=None, skip_checks: Optional[list[str]]=None) -> tuple[str, str, int]` — Scan a directory for IaC misconfigurations.
- `async def scan_file(self, path: str, frameworks: Optional[list[str]]=None, run_checks: Optional[list[str]]=None, skip_checks: Optional[list[str]]=None) -> tuple[str, str, int]` — Scan a single file for IaC misconfigurations.
- `async def scan_terraform(self, path: str, run_checks: Optional[list[str]]=None, skip_checks: Optional[list[str]]=None, download_modules: bool=True) -> tuple[str, str, int]` — Scan Terraform configurations for misconfigurations.
- `async def scan_cloudformation(self, path: str, run_checks: Optional[list[str]]=None, skip_checks: Optional[list[str]]=None) -> tuple[str, str, int]` — Scan CloudFormation templates for misconfigurations.
- `async def scan_kubernetes(self, path: str, run_checks: Optional[list[str]]=None, skip_checks: Optional[list[str]]=None) -> tuple[str, str, int]` — Scan Kubernetes manifests for misconfigurations.
- `async def scan_dockerfile(self, path: str, run_checks: Optional[list[str]]=None, skip_checks: Optional[list[str]]=None) -> tuple[str, str, int]` — Scan Dockerfile for misconfigurations.
- `async def scan_secrets(self, path: str, skip_paths: Optional[list[str]]=None) -> tuple[str, str, int]` — Scan for exposed secrets using entropy-based detection.
- `async def scan_github_actions(self, path: str, run_checks: Optional[list[str]]=None, skip_checks: Optional[list[str]]=None) -> tuple[str, str, int]` — Scan GitHub Actions workflows for misconfigurations.
- `async def list_checks(self, framework: Optional[str]=None) -> tuple[str, str, int]` — List available Checkov checks.
