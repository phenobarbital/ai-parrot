---
type: Wiki Entity
title: SecurityReportToolkit
id: class:parrot_tools.security.report_toolkit.SecurityReportToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: LLM-facing tools for querying the cross-session security report catalog.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# SecurityReportToolkit

Defined in [`parrot_tools.security.report_toolkit`](../summaries/mod:parrot_tools.security.report_toolkit.md).

```python
class SecurityReportToolkit(AbstractToolkit)
```

LLM-facing tools for querying the cross-session security report catalog.

These tools cover the **read side** of the catalog.  The write side is
handled by ``ReportPersistenceMixin`` (TASK-1109) composited into each
scanner toolkit.

Usage pattern (agent BACKSTORY instructs this flow)::

    1. find_security_report(...)  → check if a fresh report exists
    2. read_security_report(id, "summary")  → assess severity
    3. read_security_report(id, "critical")  → get critical details
    4. (only if stale / absent) → run scanner toolkit

## Methods

- `async def find_security_report(self, scanner: str | None=None, framework: str | None=None, provider: str | None=None, scope_match: dict | None=None, max_age_days: int=30, report_kind: str='scan', limit: int=5) -> list[dict]` — Find recent security reports matching the filter criteria.
- `async def read_security_report(self, report_id: str, section: Literal['summary', 'critical', 'high', 'medium', 'low', 'executive', 'full']='summary') -> dict` — Read a specific section of a security report.
- `async def search_findings(self, query: str, scanner: str | None=None, severity: Literal['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] | None=None, since_days: int=30, limit: int=20) -> list[dict]` — Search security findings across catalog reports.
- `async def list_available_frameworks(self) -> list[str]` — List compliance frameworks for which reports exist in the catalog.
