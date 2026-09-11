# TASK-3157: `sdd-worker` provisions through the shared rule

**Feature**: FEAT-552 — Worktree Creation Ownership
**Spec**: `sdd/specs/worktree-creation-ownership.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3154
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. `sdd-worker` §3 already does the right *thing* — create-or-
reuse — but hand-rolled, and with one silent defect: it always builds
`feat-<FEAT-ID>-<slug>` from `HEAD`, so a hotfix routed through the worker gets
a `feat-…` branch based on whatever is checked out, inheriting unreleased `dev`
commits. That is the exact FEAT-466 root cause (PR #1250), still live in this
file.

Replacing the block with the shared CLI fixes the naming, the base ref, and the
duplication in one edit.

---

## Scope

- Replace the body of `### 3. Create the Worktree` in
  `.claude/agents/sdd-worker.md` with a call to
  `python -m scripts.sdd.ensure_worktree`.
- Reduce `### 4. Verify SDD Files Are Visible` to a restatement of what
  `--spec`/`--index` now enforce.
- Mirror both edits byte-identically into
  `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md`.

**NOT in scope**: the Orchestrator Loop (§0 onwards) and the MCP coder-pool
sub-worktrees — those are `SubWorktreeManager`'s layer and unchanged; the other
three agents (TASK-3158).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-worker.md` | MODIFY | §3 rewired to the CLI; §4 reduced |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | Byte-identical twin |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```
.claude/agents/sdd-worker.md
  line 165  ### 2. Mark All Tasks as In-Progress (in place, on `<BASE_BRANCH>`)
  line 183  ### 3. Create the Worktree           <-- replace this section's body
  line 190  WORKTREE_NAME="feat-<FEAT-ID>-<feature-slug>"
  line 194  git worktree list | grep "${WORKTREE_NAME}" && echo "Reusing existing worktree" || \
  line 195    git worktree add -b "${WORKTREE_NAME}" "${WORKTREE_PATH}" HEAD
  line 200  ### 4. Verify SDD Files Are Visible
  line 206  ### 5. Read the Spec
```
`### 3. Create the Worktree` occurs exactly once
(verified: `grep -cF '### 3. Create the Worktree' .claude/agents/sdd-worker.md` → 1).

### The twin — byte parity is ENFORCED
`packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py` asserts each
`_subagent_data/<name>.md` is byte-identical to `.claude/agents/<name>.md`.
Both copies are identical today (verified 2026-09-11 with `cmp -s`). Edit both
or the suite goes red — `load_subagent_definition()` reads ONLY the packaged
copy, so an un-mirrored edit would also mean dev-loop dispatches the old prompt.

### Does NOT Exist
- ~~a hotfix branch in `sdd-worker` §3~~ — it has none today; the CLI supplies it
- ~~`SubWorktreeManager` as a replacement for this step~~ — it creates per-worker
  sub-worktrees *inside* the feature worktree this step provisions
  (`worktree_manager.py:78`); the two are different layers
- ~~`.agent/workflows/sdd-worker.md`~~ — `sdd-worker` is an agent, not a command;
  its twin lives under `_subagent_data/`, not `.agent/workflows/`

---

## Implementation Notes

### Key Constraints
- §3's position and heading number stay; only its body changes (renaming the
  heading to "Ensure the Worktree" is allowed and preferred, as long as it stays
  section 3 and both copies match).
- Do not delete §4 — the worker's readers rely on the explicit "STOP if missing"
  instruction. Reduce it to a restatement that the CLI now enforces it.
- The worker may run with `--dangerously-skip-permissions`; the CLI is
  non-destructive by construction (TASK-3154 AC-9), which is why it is safe here.

---

## Implementation Blueprint

### Steps (in order)
1. Replace §3's body in `.claude/agents/sdd-worker.md` — *why*: it is the
   duplicated, hotfix-blind copy of the rule.
2. Reduce §4 — *why*: two places asserting the same check will drift.
3. `cp` the edited file over the `_subagent_data/` twin — *why*: byte parity is
   asserted by a test and by what dev-loop actually dispatches.
4. Run `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q`.

### `.claude/agents/sdd-worker.md` (MODIFY)
```
# occurrences: 1 (verified: grep -cF '### 3. Create the Worktree' .claude/agents/sdd-worker.md)
# REPLACE — from `### 3. Create the Worktree` (verified: .claude/agents/sdd-worker.md:183)
#           up to but NOT including `### 4. Verify SDD Files Are Visible` (line 200)

### 3. Ensure the Worktree

Provision it through the shared rule — never hand-build the name or the base
ref (FEAT-552). The command is idempotent: it reuses an existing worktree and
creates one only when absent.

    WORKTREE_PATH=$(python -m scripts.sdd.ensure_worktree \
      --slug "<feature-slug>" \
      --feature-id "<FEAT-ID>" \
      --spec "<spec-path>" \
      --index "sdd/tasks/index/<feature-slug>.json")
    cd "$WORKTREE_PATH"

For a hotfix (`type: hotfix` in the per-spec index header) pass
`--jira-key <KEY>` instead of `--feature-id`. This is a real behaviour change:
the previous block always produced `feat-<FEAT-ID>-<slug>` from `HEAD`, so a
hotfix inherited unreleased `dev` commits (FEAT-466). Naming and base ref now
come from `scripts.sdd.sdd_meta.plan_worktree`.

If the command exits non-zero, STOP and report its message. Do not implement on
`<BASE_BRANCH>`.
```
(render the indented shell lines above as a fenced `bash` block in the file)

**Why this shape**: the worker is the unattended lane, so the failure mode it
must never have is "quietly proceed in the wrong tree". Pointing at
`plan_worktree` by name stops a future editor from re-inlining a template here.

### `.claude/agents/sdd-worker.md` §4 (MODIFY)
```
# occurrences: 1 (verified: grep -cF '### 4. Verify SDD Files Are Visible' .claude/agents/sdd-worker.md)
# REPLACE — the body between line 200 and `### 5. Read the Spec` (line 206)

### 4. Verify SDD Files Are Visible

Already enforced: §3 passed `--spec` and `--index`, and the CLI refuses to hand
back a worktree in which either is missing. If you reached this point, both are
present. A failure here means the base branch does not carry the task artifacts
yet — fetch and re-run §3 rather than working around it.
```
**Why**: keeps the reader's checkpoint without a second, drift-prone
implementation of the check.

### `_subagent_data/sdd-worker.md` (MODIFY)
```bash
cp .claude/agents/sdd-worker.md \
   packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md
cmp .claude/agents/sdd-worker.md \
    packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md
```
**Why**: the two are byte-identical today and a test says they must stay so.

### FILL IN checklist
- [ ] none — apply the blueprint verbatim, then mirror

---

## Acceptance Criteria

- [ ] `grep -c "git worktree add" .claude/agents/sdd-worker.md` returns `0`
- [ ] `.claude/agents/sdd-worker.md` references `scripts.sdd.ensure_worktree` and documents `--jira-key` for hotfixes
- [ ] `WORKTREE_NAME="feat-<FEAT-ID>-<feature-slug>"` no longer appears in the file
- [ ] `cmp .claude/agents/sdd-worker.md packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` exits 0
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q` passes
- [ ] §3 is still section 3 and §4/§5 keep their numbers

---

## Test Specification

Covered by the existing `test_subagent_parity.py`; the grep criteria become
permanent in TASK-3160.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 5, §7 "sdd-worker gains
   hotfix naming it never had")
2. **Check dependencies** — TASK-3154 in `sdd/tasks/completed/`, and
   `python -m scripts.sdd.ensure_worktree --help` exits 0
3. **Verify the Codebase Contract** — re-confirm both copies are identical
   before you start (`cmp -s`), so any diff afterwards is yours
4. **Update status** in `sdd/tasks/index/worktree-creation-ownership.json` → `"in-progress"`
5. **Implement** from the blueprint
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3157-sdd-worker-shared-rule.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
