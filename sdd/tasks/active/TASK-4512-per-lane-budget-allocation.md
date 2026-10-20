# TASK-4512: Per-lane budget allocation + `--no-parallel` flag in /sdd-proposal

**Feature**: FEAT-708 — sdd-proposal-parallel-research
**Spec**: `sdd/specs/sdd-proposal-parallel-research.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 2 (M2). Before Phase 2 can fork lanes, the command must state how a
budget profile splits into per-lane quotas and when parallelism is off. This is
the first of four tasks editing `.claude/commands/sdd-proposal.md`
(4512 → 4513 → 4514 → 4516, serialized).

## Scope

- Add `--no-parallel` to the flags list and the Usage block.
- Add a "Per-lane allocation" subsection right after the budget table (§1).
- State the sequential-forcing conditions: `tight`, `custom`, `--no-parallel`.

**NOT in scope**: dispatch mechanics (TASK-4513), twins (TASK-4517).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-proposal.md` | MODIFY | §1 flags + per-lane allocation table |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None — Markdown only.

### Existing Signatures to Use
```markdown
<!-- .claude/commands/sdd-proposal.md (verified 2026-10-20 @ 9e8092778) -->
:36   /sdd-proposal NAV-8421 --budget=loose           # tight | default | loose
:76   - **flags**: `--mode`, `--no-gate`, `--resume`, `--budget`.
:96   - `budget`: per `--budget` profile (see table below)
:98   | `--budget`  | files_read | grep_calls | git_calls | depth | wall_seconds |
:100-102  tight 15/10/5/1/120 · default 40/25/10/2/300 · loose 100/60/20/3/900
:104  ### 2. Phase 0 — Resolve Source
```

### Does NOT Exist
- ~~`--no-parallel`~~ flag — added here
- ~~`--lane-budget`~~ — explicitly out of scope (spec Non-Goals); do not add
- ~~a `custom` row in the budget table~~ — `custom` is referenced by the spec (S11); grep the file for it; if no `custom` profile is documented, write the rule as "any non-standard (custom) budget runs sequential"

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [{"path": ".claude/commands/sdd-proposal.md", "action": "MODIFY"}],
  "contract_symbols": []
}
```

## Implementation Notes

### Key Constraints
- Use `floor()` for every fraction; git lane gets 100% of `git_calls`.
- Lane wall clock is `floor(0.85 * wall_seconds)`; the rest (15%) is the merge window.
- Unused lane quota is NOT reclaimable (S3).
- Wiki queries remain free against the budget (existing rule, line ~207) — say so in the wiki row note.

## Implementation Blueprint

### Steps (in order)
1. Edit the flags line (:76) to add `--no-parallel` — because Parse Input is where flags are enumerated.
2. Add a Usage example line near :36.
3. Insert the per-lane subsection after the `loose` row (:102), before `### 2. Phase 0` — because allocation is computed when the budget is set.

### `.claude/commands/sdd-proposal.md` (MODIFY) — flags
```markdown
<!-- occurrences: 1 (verified: grep -c -- '- \*\*flags\*\*: `--mode`, `--no-gate`, `--resume`, `--budget`.' .claude/commands/sdd-proposal.md) -->
<!-- REPLACE line :76 with: -->
- **flags**: `--mode`, `--no-gate`, `--resume`, `--budget`, `--no-parallel`.
```

### `.claude/commands/sdd-proposal.md` (MODIFY) — allocation
```markdown
<!-- occurrences: 1 (verified: grep -c '^### 2. Phase 0 — Resolve Source' .claude/commands/sdd-proposal.md) -->
<!-- BEFORE — insert above `### 2. Phase 0 — Resolve Source` (verified: :104) -->
#### Per-lane allocation (parallel research, FEAT-708)

When Phase 2 runs in parallel (§4a), each of the three research lanes gets a
fixed slice of the profile. All fractions use `floor()` so the lanes together
never exceed the profile; unused quota in one lane is **not** reclaimable by
another.

| Lane | files_read | grep_calls | git_calls | depth | wall_seconds |
|------|-----------:|-----------:|----------:|------:|-------------:|
| codebase | `floor(0.60 × files_read)` | `floor(0.80 × grep_calls)` | 0 | profile | `floor(0.85 × wall_seconds)` |
| git      | `floor(0.20 × files_read)` | 0 | `git_calls` | 1 | `floor(0.85 × wall_seconds)` |
| wiki     | `floor(0.20 × files_read)` | `floor(0.20 × grep_calls)` | 0 | profile | `floor(0.85 × wall_seconds)` |

The remaining `wall_seconds − floor(0.85 × wall_seconds)` (~15%) is the
**merge window**, reserved for join + dedup + checkpoint (§4c).

Phase 2 runs **sequentially** (no lanes, no forks) when any of:
- `--budget=tight` — fork overhead is not justified for 15 files / 120 s;
- a custom budget — per-lane custom limits are not supported;
- `--no-parallel` was passed;
- the Agent tool is unavailable (detected at dispatch, §4a).
```
**Why**: verbatim spec M2 table + S3/S11 rules; §4a/§4c references land in TASK-4513/4514.

### FILL IN checklist
- [ ] Add one Usage example: `/sdd-proposal NAV-8421 --no-parallel` near :36
- [ ] Confirm how a "custom" budget is expressed in this file and phrase the bullet accordingly

## Acceptance Criteria

- [ ] `--no-parallel` documented in flags and Usage
- [ ] Allocation table matches spec M2 exactly (floor, 0.60/0.80/0.20/0.20, 0.85)
- [ ] Sequential conditions list tight, custom, `--no-parallel`, Agent unavailable
- [ ] Existing budget table unchanged

## Validation Commands

- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-proposal-parallel-research --feature-id FEAT-708`)
2. **Read the spec** at `sdd/specs/sdd-proposal-parallel-research.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/sdd-proposal-parallel-research.json`
4. **Verify the Codebase Contract** — re-run every `grep -c` anchor check before editing;
   if an anchor moved, fix the blueprint first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `FILL IN`
7. **Verify** — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (`.claude/` paths need `git add -f`)
9. **Close** with `scripts/sdd/close_task.sh <TASK-ID> sdd-proposal-parallel-research verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
