# TASK-2695: Flex KPI knowledge-base documents

**Feature**: FEAT-491 — Flex A2UI Dashboard Agent
**Spec**: `sdd/specs/flex-agent-infographic-a2ui.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (proposal U2: file-based kb docs, versioned with code, no DB
dependency). These documents are the authoritative KPI definitions that remove
computation ambiguity for the LLM at question time. The agent (TASK-2696)
loads them into its KB store at `configure()`; this task only AUTHORS them.
Content is fully determined by spec §2's resolved formulas — no code
dependency, so this task can run in parallel with TASK-2693/2694.

---

## Scope

Create one markdown doc per KPI under `agents/flex_dashboard/kb/`:

- `payroll_contribution.md` — Worked Hours (sum of `hours.hours`; pay-code/
  cost-center filterable), Payroll by Month, P&L Revenue by Month, and
  **Payroll % to Revenue = sum(Payroll) / sum(Revenue)** (denominator is
  Revenue ALONE, never Revenue + PC Revenue); currency columns arrive as
  formatted strings and are parsed by the normalization layer; month grain =
  `YYYY-MM` from finance month-end dates vs hours `month_start`.
- `pay_code_allocation.md` — Pay Code Hours and Worked Hours by Pay Code
  Allocation; source `flex_hours_query_pbi`; filterable by month, pay_code,
  cost_center.
- `rep_utilization.md` — Utilization = `employees_worked / average_active`
  per region/category/month from `fm_rep_utilization` (note the raw
  `catagory` typo column); `fm_regions_avg_employees_html`'s precomputed
  `Employee Utilization` is a cross-check only.
- `proximity_staffing.md` — per-store nearest-N employees (default 3) by
  haversine distance, configurable radius (default 50 miles); output = two
  map layers + coverage table; sources `flex_msl_brian_bi` +
  `flex_empolyees_brian_bi`.
- `datasets.md` — the six slugs, their aliases (`msl`, `finance`, `hours`,
  `employees`, `region_utilization`, `rep_utilization`), grains, quirks
  (currency strings, three date conventions, `catagory` typo), and which
  filters apply to which dataset (per-section rule).

Each doc: a short "Definition", "Formula", "Source columns",
"Normalization rules", "Filters", and "Worked example" section — the worked
example computed by hand from the sample rows in
`sdd/state/FEAT-517/source.md`.

Add a lightweight unit test asserting each doc exists and contains the
required section headers.

**NOT in scope**: loading the docs into the KB store (TASK-2696 wires
`use_kb=True` + `add_facts`); skills (TASK-2698).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/flex_dashboard/kb/payroll_contribution.md` | CREATE | KPI definition |
| `agents/flex_dashboard/kb/pay_code_allocation.md` | CREATE | KPI definition |
| `agents/flex_dashboard/kb/rep_utilization.md` | CREATE | KPI definition |
| `agents/flex_dashboard/kb/proximity_staffing.md` | CREATE | KPI definition |
| `agents/flex_dashboard/kb/datasets.md` | CREATE | dataset/alias/filter reference |
| `packages/ai-parrot/tests/unit/bots/test_flex_dashboard_kb_docs.py` | CREATE | docs exist + required sections |

---

## Codebase Contract (Anti-Hallucination)

### Consumption contract (what TASK-2696 will do with these files)
```python
# packages/ai-parrot/src/parrot/stores/kb/store.py
class KnowledgeBaseStore:
    async def add_facts(self, facts: List[Dict[str, Any]])   # line 99
    # each fact dict MUST have a "content" key; "metadata" dict optional,
    # metadata["category"] is indexed (lines 99-120)
```
Docs must therefore be plain markdown whose full text works as a single
fact `content` string (keep each under ~2-3 KB).

### Authoritative inputs
- `sdd/specs/flex-agent-infographic-a2ui.spec.md` §2 "Resolved KPI formulas".
- `sdd/state/FEAT-517/source.md` — sample rows for worked examples.

### Does NOT Exist
- ~~a kb loader that parses frontmatter or sections from these docs~~ —
  nothing in core does; the agent loads each file's full text as one fact.
- ~~`local_kb`/pgvector seeding for this agent~~ — rejected in proposal U2;
  do not write a seeder script.

---

## Implementation Notes

### Key Constraints
- Numbers in worked examples must be reproducible by hand from the sample
  rows — these docs are the anti-ambiguity anchor, so no invented figures.
- Spanish or English? Follow the repo's kb/document convention: English
  (all existing skill/kb content is English).
- Keep formulas in code-style notation (e.g. `sum(Payroll) / sum(Revenue)`).

### References in Codebase
- `.agent/skills/budget-narrative/SKILL.md` — tone/precision precedent
  ("Quote only figures present in the facts; never invent a number").

---

## Acceptance Criteria

- [ ] Five docs exist with Definition / Formula / Source columns /
      Normalization rules / Filters / Worked example sections.
- [ ] Payroll % doc states the Revenue-alone denominator explicitly.
- [ ] Utilization doc states recompute-from-`fm_rep_utilization` + cross-check rule.
- [ ] Worked examples match hand computation from the sample rows.
- [ ] Test passes: `pytest packages/ai-parrot/tests/unit/bots/test_flex_dashboard_kb_docs.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/test_flex_dashboard_kb_docs.py
from pathlib import Path
KB_DIR = Path(__file__).resolve().parents[4].parents[0]  # resolve repo root robustly
REQUIRED = ["Definition", "Formula", "Source columns", "Normalization rules",
            "Filters", "Worked example"]

def test_kb_docs_present_and_structured():
    docs = sorted((REPO_ROOT / "agents/flex_dashboard/kb").glob("*.md"))
    assert {d.name for d in docs} >= {
        "payroll_contribution.md", "pay_code_allocation.md",
        "rep_utilization.md", "proximity_staffing.md", "datasets.md"}
    for d in docs:
        text = d.read_text()
        for section in REQUIRED:
            assert section in text, f"{d.name} missing {section}"
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/flex-agent-infographic-a2ui.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-01
**Notes**: Authored all five kb docs under `agents/flex_dashboard/kb/`
(`payroll_contribution.md`, `pay_code_allocation.md`,
`rep_utilization.md`, `proximity_staffing.md`, `datasets.md`), each with
the six required sections. All worked-example numbers were computed by
hand from the single sample row per dataset in
`sdd/state/FEAT-517/source.md` (payroll % = `20682.27/137456.85`, rep
utilization = `12/63`, region cross-check = `11/75.5`, proximity haversine
distance computed via the exact formula documented in
`proximity_staffing.md` and cross-checked with a throwaway numpy snippet —
no invented figures). 4 unit tests pass; `ruff check` is clean.

**Deviations from spec**: none
