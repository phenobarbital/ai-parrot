---
type: Wiki Summary
title: parrot_tools.security.advisory_engine
id: mod:parrot_tools.security.advisory_engine
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: SecurityAdvisoryEngine — day-over-day diff and SOC2 control mapping.
relates_to:
- concept: class:parrot_tools.security.advisory_engine.AdvisoryRecommendation
  rel: defines
- concept: class:parrot_tools.security.advisory_engine.AdvisoryReport
  rel: defines
- concept: class:parrot_tools.security.advisory_engine.FindingDelta
  rel: defines
- concept: class:parrot_tools.security.advisory_engine.SecurityAdvisoryEngine
  rel: defines
- concept: func:parrot_tools.security.advisory_engine.parse_findings
  rel: defines
- concept: mod:parrot.storage.security_reports
  rel: references
- concept: mod:parrot_tools.security.models
  rel: references
- concept: mod:parrot_tools.security.parsers
  rel: references
- concept: mod:parrot_tools.security.reports
  rel: references
---

# `parrot_tools.security.advisory_engine`

SecurityAdvisoryEngine — day-over-day diff and SOC2 control mapping.

Pure-logic module: no LLM, no agent, no I/O beyond the injected store and
mapper.  The agent narrates the structured ``AdvisoryReport`` via its LLM.

Implements FEAT-226 spec §3 Module 1.

## Classes

- **`FindingDelta(BaseModel)`** — Day-over-day change for a single finding (aligned to SecurityFinding).
- **`AdvisoryRecommendation(BaseModel)`** — One actionable recommendation tied to SOC2 controls.
- **`AdvisoryReport(BaseModel)`** — Structured day-over-day SOC2 advisory for one framework.
- **`SecurityAdvisoryEngine`** — Deterministic day-over-day security advisory engine.

## Functions

- `def parse_findings(ref: ReportRef, content: bytes) -> list[SecurityFinding]` — Try to parse ``content`` into a list of SecurityFinding objects.
