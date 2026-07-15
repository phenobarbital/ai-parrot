---
type: Wiki Summary
title: parrot.storage.security_reports.models
id: mod:parrot.storage.security_reports.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic v2 data models for the cross-session security report catalog.
relates_to:
- concept: class:parrot.storage.security_reports.models.EmbeddedFinding
  rel: defines
- concept: class:parrot.storage.security_reports.models.ReportFilter
  rel: defines
- concept: class:parrot.storage.security_reports.models.ReportKind
  rel: defines
- concept: class:parrot.storage.security_reports.models.ReportRef
  rel: defines
- concept: class:parrot.storage.security_reports.models.SeverityBreakdown
  rel: defines
---

# `parrot.storage.security_reports.models`

Pydantic v2 data models for the cross-session security report catalog.

All models are pure-data (no I/O). Every consumer of the catalog — producers,
persistence layer, and the LLM-facing toolkit — imports from this module.

Key design choices:
- ``produced_at`` is tz-aware UTC. Callers are responsible for passing
  ``datetime.now(timezone.utc)``; the model does not validate timezone
  awareness at instantiation (avoids overhead on every DB load).
- ``top_findings`` is capped at 10 entries in usage; no model-level
  validator enforces this to keep the Pydantic overhead minimal.
- ``ReportFilter.since`` has no default — the store applies NO implicit
  age filter (spec §5 hard requirement).

## Classes

- **`ReportKind(str, Enum)`** — Fractal kind hierarchy: raw scans and aggregated summaries share the same shape.
- **`SeverityBreakdown(BaseModel)`** — Count container for findings by severity level.
- **`EmbeddedFinding(BaseModel)`** — A single security finding embedded in a ReportRef.
- **`ReportRef(BaseModel)`** — Canonical metadata record for any security report.
- **`ReportFilter(BaseModel)`** — Query filter for the security report store.
