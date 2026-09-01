---
name: flex-narrative
description: >
  Render deterministic Flex dashboard facts (the flex_narrative_facts
  transformer output) as short executive-summary prose. Quote only
  figures present in the facts; never invent a number.
triggers: []
category: domain
version: "1.0"
---

# Flex Program Narrative

You are given a `flex_narrative_facts` object — a structured, deterministic
summary of the Flex program dashboard. Turn it into a short executive
narrative. You are the ONLY non-deterministic step in this pipeline; the
numbers are already computed and verified (`agents/flex_dashboard/
transformers.py`). Your job is prose, not analysis.

## Fields you receive

- `worked_hours_total` — total worked hours (sum of `hours.hours`).
- `payroll_total` — total payroll (sum of `finance.Payroll`).
- `revenue_total` — total P&L revenue (sum of `finance.Revenue`).
- `payroll_pct` — `payroll_total / revenue_total` (Revenue ALONE as the
  denominator).
- `worked_hours_trend` — `"increasing"`, `"decreasing"`, or `"flat"`,
  comparing the first and last month of the Worked Hours by Month series.
- `regions_tracked` — sorted list of region names covered by the Rep
  Utilization section.

## Hard rules

1. **Never write a number that is not in the facts.** Every figure you
   write is checked mechanically after the fact — one invented figure
   discards your ENTIRE output, not just the offending sentence. When in
   doubt, name the direction (`worked_hours_trend`) or the entity
   (a region name from `regions_tracked`) instead of a figure.
2. **State direction; do not infer causes.** Say *what* the trend is; do
   not speculate about *why* the hours are increasing/decreasing/flat
   beyond what the facts carry.
3. **Format money and percentages using the house style**: `$1.23M` /
   `$45.6K` for dollars, `12.3%` for percentages (`payroll_pct` is a
   ratio — multiply by 100 for display, never invent extra precision).
4. **If `regions_tracked` is empty**, omit any sentence naming regions
   rather than padding with a placeholder.

## What to produce

Write two short sections, matching what the layout binds to:

1. **Headline** (1-2 sentences): worked hours, payroll, and revenue
   totals, and the payroll % to revenue figure.
2. **Trend** (1 sentence): the `worked_hours_trend` direction, naming
   the tracked regions (`regions_tracked`) if any.

If a section's driving field is absent or empty, omit that section
entirely rather than padding it with a placeholder sentence.
