---
type: Wiki Entity
title: SecurityAdvisoryEngine
id: class:parrot_tools.security.advisory_engine.SecurityAdvisoryEngine
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Deterministic day-over-day security advisory engine.
---

# SecurityAdvisoryEngine

Defined in [`parrot_tools.security.advisory_engine`](../summaries/mod:parrot_tools.security.advisory_engine.md).

```python
class SecurityAdvisoryEngine
```

Deterministic day-over-day security advisory engine.

Given a ``SecurityReportStore`` and an optional ``ComplianceMapper``,
fetches the two most-recent reports for a framework, diffs their findings,
maps the delta to SOC2 controls via the existing ``ComplianceMapper``,
and returns a structured ``AdvisoryReport`` Pydantic model.

No narrative is written here — the caller's LLM generates prose.

Example:
    engine = SecurityAdvisoryEngine(report_store=store)
    report = await engine.build_daily_advisory(framework="soc2")

## Methods

- `async def build_daily_advisory(self, *, framework: str, provider: str='aws') -> AdvisoryReport` — Build a day-over-day SOC2 advisory for one framework.
