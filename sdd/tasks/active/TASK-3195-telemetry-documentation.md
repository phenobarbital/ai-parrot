# TASK-3195: Document the telemetry campaign workflow

**Feature**: FEAT-554 — Empirical Token-Budget Sizing for sdd-coder Bedrock Seats
**Spec**: `sdd/specs/sdd-coder-bedrock-token-telemetry.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3187, TASK-3190, TASK-3193, TASK-3194
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 and AC-18. `docs/dev_loop/sdd-coder-orchestrator.md` already has
a "Telemetry" section describing what an attempt records. It now needs the
campaign workflow, the row schema, and one warning that no reader can be allowed
to miss: **a coding attempt's cumulative budget is measured in millions of
tokens, not in context-window units.** An operator who sets `token_budget` to a
context-window-sized number kills every attempt around turn 11.

---

## Scope

- Replace the "Telemetry" section of `docs/dev_loop/sdd-coder-orchestrator.md`
  with: how to enable a campaign, what the two row kinds contain, how to run the
  analysis, and the millions-not-thousands warning with its measured numbers.
- Note that the `gemini` seat records provider totals only, with no `ledger_*`
  fields, and why.

**NOT in scope**: any code, the spec itself, README changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/dev_loop/sdd-coder-orchestrator.md` | MODIFY | Rewrite the Telemetry section |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
*(none — documentation only)*

### Existing Signatures to Use
```
# docs/dev_loop/sdd-coder-orchestrator.md
## Telemetry            <-- the section to replace
## Troubleshooting      <-- the section that follows it; do not disturb

# Settings, as implemented by TASK-3190 (parrot/conf.py)
DEV_LOOP_CODER_TELEMETRY: bool   # master switch, default False
DEV_LOOP_CODER_LEDGER: bool      # bind the observational ledger, default True
SDD_CODER_TELEMETRY_DIR: str     # absolute durable dir, "" = derive main checkout

# Measured figures to quote (artifacts/logs/sdd-coder-count-input-overhead-20260912.md)
#   60-turn attempt, history to ~148k tokens:
#     cumulative question total ~4.7M tokens (~5.1M if every turn saturates max_tokens)
#     count_input overhead: 4.9 ms at turn 1, 65 ms at turn 60, 2.77 s per attempt
#   MCP roster path runs at max_turns=60 (agent_builder.py:134), not the profile default of 24
```

### Does NOT Exist
- ~~`DEV_LOOP_CODER_SHADOW_BUDGET`~~ — there is no ceiling knob; observational mode
  admits everything. Do not document one.
- ~~A `cost` column in the dataset~~ — pricing is out of scope.
- ~~Ledger coverage for the `gemini` seat~~ — `GeminiOpenAICompatClient` defines no
  budget adapter, so that seat is the unbudgeted comparison baseline.

---

## Implementation Notes

### Key Constraints
- Lead the section with the scale warning. It is the single most likely
  operational mistake and burying it in a table guarantees it happens.
- Quote the measured numbers with their source file, not as round estimates.
- Keep the existing section's register: short, imperative, table-first.

### References in Codebase
- `docs/dev_loop/sdd-coder-orchestrator.md` — the "Outcomes" and "Branches &
  worktrees" sections show the house style to match.

---

## Implementation Blueprint

### Steps (in order)
1. Replace the Telemetry section body, keeping the `## Telemetry` heading — *why*: other docs and the spec link to that anchor.
2. Open with the scale warning — *why*: AC-18 is specifically about this, and it is the one thing a reader must not skim past.
3. Add the enable/collect/analyse walkthrough and the row-kind table — *why*: an operator running a campaign needs the whole loop in one place.

### `docs/dev_loop/sdd-coder-orchestrator.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '^## Telemetry' docs/dev_loop/sdd-coder-orchestrator.md)
# REPLACE the body between `## Telemetry` and `## Troubleshooting`
# (verified: docs/dev_loop/sdd-coder-orchestrator.md — run
#  `grep -n '^## Telemetry' -A 8 docs/dev_loop/sdd-coder-orchestrator.md` first)

> **A coding attempt's cumulative token budget is measured in MILLIONS.** A
> 60-turn attempt whose history grows to ~148k tokens consumes ~4.7M cumulative
> tokens (~5.1M if every turn saturates `max_tokens`), because the full history
> is re-sent every turn and the MCP roster path runs at `max_turns=60`
> (`agent_builder.py:134`), not the profile default of 24. `token_budget` is
> NOT a context-window setting: 200,000 would kill every attempt around turn 11.
> Measurements: `artifacts/logs/sdd-coder-count-input-overhead-20260912.md`.

# FILL IN: the campaign walkthrough — (1) enable with the three settings,
# (2) run features normally, (3) run scripts/analyze_sdd_coder_usage.py, and a
# table of the two row kinds and their key fields. Bounded by AC-18 and by the
# existing section's register (short, imperative, table-first).
```
**Why**: The warning is a blockquote at the top because it is the operational
trap; everything else in the section is reference material a reader consults.

### FILL IN checklist
- [ ] `sdd-coder-orchestrator.md::Telemetry` — the campaign walkthrough and row-kind table; bounded by AC-18

---

## Acceptance Criteria

- [ ] The `## Telemetry` heading and the `## Troubleshooting` section that follows are intact.
- [ ] The section states the millions-not-thousands fact with the measured figures and cites the evidence file.
- [ ] The three settings are documented with their defaults; no ceiling knob is mentioned.
- [ ] The dataset location and the two row kinds are described, including that they join on `attempt_uid`.
- [ ] The `gemini` seat's provider-totals-only behaviour is explained.
- [ ] `python scripts/analyze_sdd_coder_usage.py --help` matches the documented invocation.

---

## Test Specification

*(Documentation task — verification is by review against the acceptance criteria. Optionally add a docs link-check to CI, out of scope here.)*

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §1 Problem Statement, §3 Module 6, §7 Known Risks.
2. **Check dependencies** — TASK-3187, TASK-3190, TASK-3193 and TASK-3194 must be in `sdd/tasks/completed/`; document what shipped, not what was planned.
3. **Verify the Codebase Contract** — confirm the setting names and the analysis script's CLI as implemented.
4. **Update status** in `sdd/tasks/index/sdd-coder-bedrock-token-telemetry.json` → `"in-progress"`.
5. **Implement** from the blueprint; keep the heading anchors.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3195-telemetry-documentation.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
