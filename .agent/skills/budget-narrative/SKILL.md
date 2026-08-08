---
name: budget-narrative
description: >
  Render deterministic budget-variance facts (the narrative_facts transformer
  output) as short executive-summary prose. Quote only figures present in the
  facts; never invent a number.
triggers: []
category: domain
version: "1.0"
---

# Budget Variance Narrative

You are given a `narrative_facts` object — a structured, deterministic
summary of a budget-variance dashboard. Turn it into a short executive
narrative. You are the ONLY non-deterministic step in this pipeline; the
numbers are already computed and verified. Your job is prose, not analysis.

## Hard rules

1. **Never write a number that is not in the facts.** Every figure you write
   is checked mechanically after the fact — one invented figure discards
   your ENTIRE output, not just the offending sentence. When in doubt, name
   the direction or the entity instead of a figure.
2. **State direction and name entities; do not infer causes.** Say *what*
   changed and *who* drove it. Do not speculate about *why* beyond what the
   facts carry (e.g. `urgency`, `kind`).
3. **If a value is `null`, say what the facts actually support** — e.g. a
   `trend` of `null` means "new this period", never a guessed number.
4. **Format money and percentages using the house style**: `$1.23M` /
   `$45.6K` for dollars, `+12.3%` / `−12.3%` for percentages (real minus
   sign, not a hyphen). Read `reference.md` for worked examples.

## What to read

- `facts-schema.md` — every field of `narrative_facts` and its allowed
  values. Read this FIRST if any field's meaning is unclear.
- `reference.md` — the house phrasing style, mapped from each fact
  combination to the sentence shape it produces. Figures there are
  fake placeholders (`$X.XM`) — never copy them as real numbers.

## What to produce

Write four short sections, matching what the layout binds to:

1. **Headline** (1-2 sentences): the overall revenue/EBITDA read, using
   `headline.rev_state`, `headline.rev_direction`, `headline.ebitda_direction`
   and the `both_improving`/`both_worsening`/`diverging` flags.
2. **Division reads** (1 sentence per entry in `division_reads`): describe
   each division's `kind` (`on_track` / `spread` / `concentrated` /
   `offset_by`), naming `named` projects and, for `offset_by`, the
   `offsetter`.
3. **Key driver** (1-2 sentences, only if `top_driver` is not `null`): name
   the division/project, its `ebitda_variance`, and its `trend`.
4. **Recommendation** (1 sentence, only if `top_driver` is not `null`): the
   action implied by `top_driver.urgency` (`immediate` / `confirm_trend` /
   `check_timing`).

If a section's driving field is absent or empty (e.g. `top_driver is null`,
or `division_reads` is empty), omit that section entirely rather than
padding it with a placeholder sentence.
