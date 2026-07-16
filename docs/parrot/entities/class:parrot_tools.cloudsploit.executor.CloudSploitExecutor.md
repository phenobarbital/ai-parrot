---
type: Wiki Entity
title: CloudSploitExecutor
id: class:parrot_tools.cloudsploit.executor.CloudSploitExecutor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Executes CloudSploit scans via Docker or direct CLI.
---

# CloudSploitExecutor

Defined in [`parrot_tools.cloudsploit.executor`](../summaries/mod:parrot_tools.cloudsploit.executor.md).

```python
class CloudSploitExecutor
```

Executes CloudSploit scans via Docker or direct CLI.

Supports two execution modes:
- Docker mode (default): runs CloudSploit inside a Docker container
- Direct CLI mode: runs CloudSploit directly via Node.js CLI

AWS credentials are passed via environment variables only,
never written to files.

## Methods

- `async def execute(self, args: list[str], volume_mounts: Optional[list[tuple[str, str, Optional[str]]]]=None) -> tuple[str, str, int]` — Run CloudSploit and return output.
- `async def run_scan(self, plugins: Optional[list[str]]=None, ignore_ok: bool=False, suppress: Optional[list[str]]=None, capture_collection: bool=True, config: Optional[str]=None) -> tuple[str, str, str, str, int]` — Run a full or targeted CloudSploit scan.
- `async def run_compliance_scan(self, framework: ComplianceFramework, ignore_ok: bool=True, capture_collection: bool=True, config: Optional[str]=None) -> tuple[str, str, str, str, int]` — Run a compliance-filtered CloudSploit scan.
