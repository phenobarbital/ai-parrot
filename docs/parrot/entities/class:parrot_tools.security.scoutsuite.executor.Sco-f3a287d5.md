---
type: Wiki Entity
title: ScoutSuiteExecutor
id: class:parrot_tools.security.scoutsuite.executor.ScoutSuiteExecutor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Executes ScoutSuite security scans.
relates_to:
- concept: class:parrot_tools.security.base_executor.BaseExecutor
  rel: extends
---

# ScoutSuiteExecutor

Defined in [`parrot_tools.security.scoutsuite.executor`](../summaries/mod:parrot_tools.security.scoutsuite.executor.md).

```python
class ScoutSuiteExecutor(BaseExecutor)
```

Executes ScoutSuite security scans.

ScoutSuite CLI pattern: `scout <provider> [options]`

Example:
    scout aws --report-dir ./aws-scan-2023-12-18 \
              --report-name aws-report \
              --result-format json \
              --access-key-id ACCESS_KEY_ID \
              --secret-access-key SECRET_KEY

## Methods

- `async def run_scan(self, provider: Optional[str]=None, services: Optional[list[str]]=None, regions: Optional[list[str]]=None, report_name: Optional[str]=None, report_dir: Optional[str]=None) -> tuple[str, str, int]` — Run a ScoutSuite security scan.
- `async def run_scan_streaming(self, progress_callback=None, provider: Optional[str]=None, services: Optional[list[str]]=None, regions: Optional[list[str]]=None, report_name: Optional[str]=None, report_dir: Optional[str]=None) -> tuple[str, str, int]` — Run a ScoutSuite scan with real-time stderr streaming.
