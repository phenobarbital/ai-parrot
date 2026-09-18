# TASK-3395: Retarget `/sdd-next` ledger section to `/sdd-fix`; deprecation pointer on `/sdd-task --from-issue`

**Feature**: FEAT-572 — `/sdd-fix` Ledger-Driven Fix Lane
**Spec**: `sdd/specs/sdd-fix-ledger-lane.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §1 Problem 2, §3 Module 5 ("retargeting"), §5, design research S9. Today `/sdd-next`'s
"Ready ledger issues" section suggests `/sdd-task --from-issue <id> <spec.md>`, which appends
a task to an existing — for all 15 current issues, *finished* — feature. `/sdd-fix`
**replaces** `--from-issue` as the ledger entry point. `--from-issue` itself keeps working for
one deprecation cycle (§1 Non-Goals) but must point at `/sdd-fix`.

Six files, two groups of three twins. No dependency on the `/sdd-fix` files themselves: this
task edits only pointers, and the parity tests for the new wording live in TASK-3396.

---

## Scope

- In the three `/sdd-next` twins, replace the `--from-issue` suggestion line with a
  `/sdd-fix` pointer; keep `wikitoolkit ledger ready` and the "Ready ledger issues" wording
  (existing `TestStartNextTwins` asserts both).
- In the three `/sdd-task` twins, add a one-paragraph **Deprecated** note to the
  `--from-issue` block pointing at `/sdd-fix`; keep `--from-issue`, `reserve_ids` and
  `discovered_from` present (existing test asserts them).

**NOT in scope**: creating `/sdd-fix` (TASK-3394); tests (TASK-3396); docs (TASK-3398);
removing `--from-issue` (a later feature).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-next.md` | MODIFY | suggestion line → `/sdd-fix` |
| `.agent/workflows/sdd-next.md` | MODIFY | suggestion line → `/sdd-fix` |
| `.agents/skills/sdd-next/SKILL.md` | MODIFY | bullet → `sdd-fix` |
| `.claude/commands/sdd-task.md` | MODIFY | Deprecated note after the `--from-issue` block |
| `.agent/workflows/sdd-task.md` | MODIFY | Deprecated note after the `--from-issue` block |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | Deprecated sub-bullet |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
*(markdown task — none)*

### Existing Signatures to Use
```text
# .claude/commands/sdd-next.md:96-107 and .agent/workflows/sdd-next.md:96-107 (identical):
### 7. Show Ready Ledger Issues (FEAT-566, best-effort)
…
wikitoolkit ledger ready 2>/dev/null || true
…
🗒  Ready ledger issues (not yet promoted to a task):
  issue:3f8a1c9e [major] Leak in connection pool (bug)
     → /sdd-task --from-issue issue:3f8a1c9e <spec.md>  (promote, keeps ID/dependency discipline)     ← line 107, REPLACE

# .agents/skills/sdd-next/SKILL.md:38-42:
7. (FEAT-566, best-effort) Show ready ledger issues:
   - `wikitoolkit ledger ready 2>/dev/null || true`
   - list open, unclaimed issues (discovered work with no TASK-NNN yet)
   - each entry suggests `sdd-task --from-issue <id> <spec.md>` to promote                              ← line 41, REPLACE

# .claude/commands/sdd-task.md:234-243 and .agent/workflows/sdd-task.md:238-247: the `--from-issue` paragraph ends with
   automatically — that stays an explicit, separate step for the human/agent
   doing the promotion.                                                                                 ← anchor (1 occurrence each)

# .agents/skills/sdd-task/SKILL.md:126-131: sub-bullet ends with
     explicit step once the task is filed.                                                              ← anchor (1 occurrence)

# tests/sdd/test_ledger_workflow_twins.py::TestStartNextTwins (MUST keep passing):
#   next twins: "ledger ready" in content; "Ready ledger issues" or "ready ledger issues" in content
#   task twins: "--from-issue", "reserve_ids", "discovered_from" in content
```

### Does NOT Exist
- ~~`/sdd-fix` files~~ — created by TASK-3394; this task only *mentions* the command.
- ~~a `--from-issue` flag on `/sdd-fix`~~ — `/sdd-fix <issue-id>` takes the id positionally.
- ~~removal of `--from-issue`~~ — out of scope (one deprecation cycle).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/commands/sdd-next.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-next.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-next/SKILL.md", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-task.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-task.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-task/SKILL.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- After the edit, no `/sdd-next` twin may contain the string `sdd-task --from-issue`
  (TASK-3396 asserts absence) while still containing `ledger ready` and `Ready ledger issues`.
- Every `/sdd-task` twin must contain both `Deprecated` (capitalised) and `/sdd-fix`, AND
  still contain `--from-issue`, `reserve_ids`, `discovered_from`.
- The `.agents/skills/sdd-task/SKILL.md` twin is the concurrent-run-sensitive file that
  `/sdd-task` itself reads; keep the edit to the one sub-bullet.

### References in Codebase
- `tests/sdd/test_ledger_workflow_twins.py:131-173` — the assertions that constrain the wording.

---

## Implementation Blueprint

### Steps (in order)
1. Replace the suggestion line in both `sdd-next.md` twins — *why*: S9, the operator path must name the new entry point.
2. Replace the Codex `sdd-next` bullet — *why*: three twins, one behaviour.
3. Append the Deprecated note in the three `sdd-task` twins — *why*: `--from-issue` keeps working but must not be the discoverable path.

### `.claude/commands/sdd-next.md` and `.agent/workflows/sdd-next.md` (MODIFY — identical edit)
```markdown
# occurrences: 1 each (verified: grep -cF '     → /sdd-task --from-issue issue:3f8a1c9e <spec.md>  (promote, keeps ID/dependency discipline)' <file>)
# REPLACE that line (verified: :107 in both) with:
     → /sdd-fix issue:3f8a1c9e        (plan-fix routes its group to the Fast or SDD lane; replaces /sdd-task --from-issue, FEAT-572)
```
> Note the replacement deliberately contains `/sdd-task --from-issue` **with a slash** but never the bare
> `sdd-task --from-issue` — TASK-3396 asserts the latter's absence. If you prefer, drop the parenthetical clause.

### `.agents/skills/sdd-next/SKILL.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -cF '   - each entry suggests `sdd-task --from-issue <id> <spec.md>` to promote' .agents/skills/sdd-next/SKILL.md)
# REPLACE that line (verified: :41) with:
   - each entry suggests `sdd-fix <id>` (FEAT-572: plan-fix routes the issue's group to the Fast or SDD lane)
```

### `.claude/commands/sdd-task.md` and `.agent/workflows/sdd-task.md` (MODIFY — identical edit)
```markdown
# occurrences: 1 each (verified: grep -cF '   doing the promotion.' <file>)
# AFTER — insert below `   doing the promotion.` (verified: :243 / :247), keeping the 3-space indent of the block:

   **Deprecated (FEAT-572)**: `--from-issue` remains for one deprecation cycle but is no
   longer the ledger entry point — it can only append a task to an *existing* spec, which
   for a finished feature (per-spec index `completed_at` set) is wrong. Use `/sdd-fix
   <issue-id>` instead: it plans the issue's group, routes it to the Fast lane (branch → PR)
   or the SDD lane (reuse the open parent spec, else mint a fresh `FEAT-<NNN>`), and closes
   by evidence.
```

### `.agents/skills/sdd-task/SKILL.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -cF '     explicit step once the task is filed.' .agents/skills/sdd-task/SKILL.md)
# AFTER — insert below that line (verified: :131), same 5-space indent:
     Deprecated (FEAT-572): prefer `sdd-fix <issue-id>`, which routes the issue's group to
     the Fast or SDD lane; `--from-issue` stays for one deprecation cycle only.
```
**Why**: the Deprecated paragraph names the reason (finished parent) so a reader understands
why the old path is wrong, not just that it is discouraged.

### FILL IN checklist
- [ ] none — all six edits are fully specified; verify with the greps in Key Constraints

---

## Acceptance Criteria

- [ ] No `/sdd-next` twin contains `sdd-task --from-issue`; all three contain `/sdd-fix` or `sdd-fix`, `ledger ready` and "Ready ledger issues".
- [ ] All three `/sdd-task` twins contain `Deprecated`, `sdd-fix`, and still `--from-issue`, `reserve_ids`, `discovered_from`.
- [ ] `--from-issue` still works (no procedural text removed).
- [ ] `pytest tests/sdd/test_ledger_workflow_twins.py -v` passes (TestStartNextTwins unchanged).

---

## Validation Commands

- `pytest tests/sdd/test_ledger_workflow_twins.py -q`

---

## Test Specification

```python
# Enforced by TASK-3396 (tests/sdd/test_ledger_workflow_twins.py::TestSddNextRetarget):
def test_all_sdd_next_twins_point_at_sdd_fix(self): ...            # "sdd-fix" in content; "sdd-task --from-issue" not in content
def test_all_sdd_task_twins_carry_from_issue_deprecation(self): ... # "Deprecated" and "sdd-fix" in content; "--from-issue" still present
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 5 "retargeting", §5 the two twin ACs, §9 S9).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — each anchor occurs exactly once.
4. **Update status** in `sdd/tasks/index/sdd-fix-ledger-lane.json` → `"in-progress"`.
5. **Implement** the six edits.
6. **Verify** the Validation Command.
7. **Move this file** to `sdd/tasks/completed/TASK-3395-retarget-next-and-deprecate-from-issue.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
