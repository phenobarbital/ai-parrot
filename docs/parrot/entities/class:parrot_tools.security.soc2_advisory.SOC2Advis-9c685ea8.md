---
type: Wiki Entity
title: SOC2AdvisoryToolkit
id: class:parrot_tools.security.soc2_advisory.SOC2AdvisoryToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: LLM-facing tools for SOC2-oriented security advisory.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# SOC2AdvisoryToolkit

Defined in [`parrot_tools.security.soc2_advisory`](../summaries/mod:parrot_tools.security.soc2_advisory.md).

```python
class SOC2AdvisoryToolkit(AbstractToolkit)
```

LLM-facing tools for SOC2-oriented security advisory.

Provides three read-only tools (``soc2_`` prefix):

- ``soc2_map_report_to_soc2`` — map a stored report's findings to
  SOC2 controls via ``ComplianceMapper.get_findings_by_control``.
- ``soc2_soc2_gap_analysis`` — coverage + unmapped findings from the
  latest SCAN report for a framework.
- ``soc2_daily_soc2_advisory`` — day-over-day diff advisory via
  ``SecurityAdvisoryEngine.build_daily_advisory``.

All tools return JSON-serialisable dicts.  On error they return
``{"error": "...", "hint": "..."}`` and never raise to the LLM.

Args:
    report_store: Required catalog backend (read-only).
    mapper: Optional ``ComplianceMapper``; a fresh default instance
        is created when not provided.
    **kwargs: Forwarded to ``AbstractToolkit.__init__``.

## Methods

- `async def map_report_to_soc2(self, report_id: str) -> dict` — Map findings from a stored report to SOC2 Trust Service Criteria.
- `async def soc2_gap_analysis(self, framework: str='soc2') -> dict` — Analyse SOC2 coverage gaps from the latest report for a framework.
- `async def daily_soc2_advisory(self, framework: str='soc2', provider: str='aws') -> dict` — Produce a day-over-day SOC2 advisory for a framework.
