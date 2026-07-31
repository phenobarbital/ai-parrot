---
type: Wiki Summary
title: parrot_tools.security.summarizer
id: mod:parrot_tools.security.summarizer
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Weekly and monthly security report summarizers.
relates_to:
- concept: class:parrot_tools.security.summarizer.MonthlySecuritySummarizer
  rel: defines
- concept: class:parrot_tools.security.summarizer.MonthlySummary
  rel: defines
- concept: class:parrot_tools.security.summarizer.WeeklySecuritySummarizer
  rel: defines
- concept: class:parrot_tools.security.summarizer.WeeklySummary
  rel: defines
- concept: mod:parrot.storage.security_reports
  rel: references
---

# `parrot_tools.security.summarizer`

Weekly and monthly security report summarizers.

Deterministic Python math (severity totals + finding set-diffs) combined
with a single LLM call for the executive paragraph.

Implements Spec §3 Module 8.

## Classes

- **`WeeklySummary(BaseModel)`** — A week-scoped security posture summary for one (provider, framework) pair.
- **`MonthlySummary(BaseModel)`** — A month-scoped security posture summary for one (provider, framework) pair.
- **`WeeklySecuritySummarizer`** — Produces a ``WeeklySummary`` from a list of scan ``ReportRef``s.
- **`MonthlySecuritySummarizer`** — Produces a ``MonthlySummary`` from a list of weekly ``WeeklySummary`` objects.
