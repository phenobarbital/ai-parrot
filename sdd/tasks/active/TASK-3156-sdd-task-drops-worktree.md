# TASK-3156: `/sdd-task` stops creating worktrees

**Feature**: FEAT-552 — Worktree Creation Ownership
**Spec**: `sdd/specs/worktree-creation-ownership.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 — the change the whole feature is named after. `/sdd-task` §6
(`.claude/commands/sdd-task.md:313`) creates the worktree right after committing
the task files. Task files are versioned state that travels through git to
another machine; a worktree is machine-local. When the two are produced in the
same step, every `/sdd-task` run on a planning machine leaves a checkout nobody
will ever enter — 13 of them are live in this clone today.

This task removes §6 and points the operator at `/sdd-start`.

---

## Scope

- Delete `### 6. Create the Worktree` from `.claude/commands/sdd-task.md`.
- Renumber `### 7. Output` → `### 6. Output` and rewrite its "Worktree created"
  stanza and "Next" block.
- Apply the same edit to the twin `.agent/workflows/sdd-task.md` AND heal the
  pre-existing drift between the two files (see Codebase Contract), so
  `tests/sdd_scripts/test_command_twin_parity.py[sdd-task]` goes green.

**NOT in scope**: `/sdd-start` (TASK-3155); the guardrail bullet in §Guardrails
that says *"Always commit task files and per-spec index to `base_branch` before
creating the worktree"* — reword only its trailing clause, do not delete the
commit rule; `CLAUDE.md` (TASK-3159).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-task.md` | MODIFY | Delete §6, renumber §7→§6, rewrite output |
| `.agent/workflows/sdd-task.md` | MODIFY | Same edit + heal pre-existing drift |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```
.claude/commands/sdd-task.md
  line  19  - Mark tasks that can run in parallel worktrees with `parallel: true`.
  line  28  - **Always commit task files and per-spec index to `base_branch`** before creating the worktree.
  line 286  ### 5. Commit Tasks and Per-Spec Index to `<BASE>`
  line 313  ### 6. Create the Worktree          <-- DELETE through line 329
  line 330  ### 7. Output                        <-- becomes "### 6. Output"
  line 352  Worktree created:                    <-- rewrite this stanza
  line 357  cd .claude/worktrees/<worktree-name>
  line 361  ## Reference
```
Every anchor above occurs exactly once (verified with `grep -cF`).

### The twin and its parity test — READ THIS BEFORE EDITING
`tests/sdd_scripts/test_command_twin_parity.py` asserts
`.agent/workflows/sdd-task.md` is byte-identical to `.claude/commands/sdd-task.md`
modulo (a) the twin's leading frontmatter and (b) exactly one substitution
(`test_command_twin_parity.py:31-33`):
```
original: (sub-features extend a parent feature branch — see `CLAUDE.md`).
twin:     (sub-features extend a parent feature branch — see `AGENTS.md`).
```
That line lives in §1 and is untouched by this task — do not disturb it.

**This test is ALREADY FAILING on `dev` before you start** (verified 2026-09-11:
`1 failed, 1 passed`). The twin is stale by two blocks that landed in the
original under FEAT-545:
The twin is missing, immediately after its `### 7. Output` heading, the
paragraph "Before printing the summary, count the delegation-eligible tasks…"
together with the fenced `grep -l '^## Delegation Contract' sdd/tasks/active/TASK-*.md | wc -l`
block; and, inside the output sample, the two lines following
`Blueprints: <N>/<N> tasks carry an Implementation Blueprint`:

    Delegated:  <D>/<N> tasks carry a Delegation Contract (targeted writer)
                TASK-<NNN>, TASK-<NNN>          # list them, or "none"

Reproduce the exact drift for yourself before editing:

    python - <<'PY'
    import difflib
    from pathlib import Path
    def strip(t):
        if not t.startswith("---\n"): return t
        e = t.find("\n---\n", 4)
        return t if e == -1 else t[e+len("\n---\n"):].lstrip("\n")
    o = Path(".claude/commands/sdd-task.md").read_text().replace(
      "(sub-features extend a parent feature branch — see `CLAUDE.md`).",
      "(sub-features extend a parent feature branch — see `AGENTS.md`).").strip()
    tw = strip(Path(".agent/workflows/sdd-task.md").read_text()).strip()
    print("\n".join(difflib.unified_diff(tw.splitlines(), o.splitlines(),
                                          "twin", "original", n=1, lineterm="")))
    PY

You did not cause this. Fix it as part of this task — otherwise the feature's
"suite is green" criterion can never be met. The reliable way: make the edits in
`.claude/commands/sdd-task.md` first, then regenerate the twin body from it and
re-apply the one documented substitution plus the twin's own frontmatter.

### Does NOT Exist
- ~~`### 8. …` in sdd-task.md~~ — the file has sections 1-7 today, 1-6 after this
- ~~a second `git worktree add` elsewhere in sdd-task.md~~ — §6 holds both (the
  feature and hotfix variants) and is the only one
- ~~`/sdd-task` creating the worktree for the dev-loop~~ — `sdd-planner` and
  `sdd-research` create their own (TASK-3158); removing §6 does not strand them

---

## Implementation Notes

### Key Constraints
- The §Guardrails bullet at line 28 must keep its commit requirement. Reword the
  trailing clause only: task files still MUST be committed to `base_branch` —
  now so that *the machine that implements* can pull them, not so that a
  worktree created seconds later inherits them.
- Renumbering is exactly one heading. Do not renumber §1-§5.
- `/sdd-task`'s own run for FEAT-552 already created a worktree — that is the
  old behaviour and is expected. Do not delete it as part of this task
  (spec §1 Non-Goals: nothing existing is removed).

---

## Implementation Blueprint

### Steps (in order)
1. Delete §6 and renumber §7 in `.claude/commands/sdd-task.md` — *why*: this is
   the behaviour change; everything else in the task is propagation.
2. Rewrite the output stanza — *why*: an operator who is told "Worktree created"
   and given a `cd` will look for a directory that no longer exists.
3. Reword the guardrail clause at line 28 — *why*: it currently states the
   removed step as the reason for committing.
4. Regenerate the twin from the edited original and re-apply the documented
   substitution — *why*: it both propagates this change and heals the FEAT-545
   drift in one stroke.
5. Run the parity test — *why*: it must go from `1 failed, 1 passed` to `2 passed`.

### `.claude/commands/sdd-task.md` (MODIFY — deletion)
```markdown
# occurrences: 1 (verified: grep -cF '### 6. Create the Worktree' .claude/commands/sdd-task.md)
# DELETE — from `### 6. Create the Worktree` (verified: .claude/commands/sdd-task.md:313)
#          through the closing fence of its second code block (line 329),
#          i.e. everything up to but NOT including `### 7. Output` (line 330).
# Then RENAME that heading:  `### 7. Output`  ->  `### 6. Output`
```
**Why**: §6 is self-contained — a heading, one paragraph, one fenced block with
both variants. Nothing later in the file refers back to it except the output
stanza rewritten below.

### `.claude/commands/sdd-task.md` (MODIFY — output stanza)
```markdown
# occurrences: 1 (verified: grep -cF 'Worktree created:' .claude/commands/sdd-task.md)
# REPLACE — the `Worktree created:` stanza and the `Next:` block that follows it
#           (verified: .claude/commands/sdd-task.md:352-358), inside the output fence

Worktree: not created. /sdd-task produces versioned artifacts only — the
          worktree is created by whoever implements, on the machine that
          implements (FEAT-552).

Next:
  /sdd-start <task-id>        # creates the worktree, then begins the task
  # or, unattended:  claude --agent sdd-worker --model sonnet --verbose
```
**Why**: the old block handed the operator a `cd` into a path this command no
longer produces. Naming both lanes keeps the unattended path discoverable, since
`sdd-worker` also provisions its own worktree (TASK-3157).

### `.claude/commands/sdd-task.md` (MODIFY — guardrail)
```markdown
# occurrences: 1 (verified: grep -cF '**Always commit task files and per-spec index to `base_branch`**' .claude/commands/sdd-task.md)
# REPLACE — line 28

- **Always commit task files and per-spec index to `base_branch`** — they are
  versioned artifacts, and the machine that implements the feature pulls them
  from there. This command creates no worktree (FEAT-552).
```
**Why**: keeps the mandatory commit, drops the removed justification.

### `.agent/workflows/sdd-task.md` (MODIFY)
```bash
# Regenerate the twin body from the edited original, preserving the twin's
# frontmatter and applying the ONE documented substitution.
# FILL IN: script or hand-apply the three edits above plus the two FEAT-545
#   blocks quoted in the Codebase Contract — bounded by AC-6 (the parity test
#   must report 2 passed). Verify with:
#     pytest tests/sdd_scripts/test_command_twin_parity.py -q
```
**Why**: hand-editing a 350-line twin to byte-identity is error-prone; derive it
from the original and let the test confirm.

### FILL IN checklist
- [ ] `.agent/workflows/sdd-task.md` — regenerate body + heal FEAT-545 drift; bounded by AC-6

---

## Acceptance Criteria

- [ ] AC-1 `grep -c "git worktree add" .claude/commands/sdd-task.md` returns `0`
- [ ] AC-2 `.claude/commands/sdd-task.md` has headings `### 1.` … `### 6.`, each exactly once, with no `### 7.`
- [ ] AC-3 The output block says the worktree is NOT created and points at `/sdd-start`
- [ ] AC-4 The §Guardrails bullet still requires committing task files and the index to `base_branch`
- [ ] AC-5 `grep -cF "(sub-features extend a parent feature branch — see \`CLAUDE.md\`)." .claude/commands/sdd-task.md` still returns `1` (the twin-substitution anchor survives)
- [ ] AC-6 `pytest tests/sdd_scripts/test_command_twin_parity.py -q` reports `2 passed` (baseline before this task: `1 failed, 1 passed`)
- [ ] AC-7 `grep -c "git worktree add" .agent/workflows/sdd-task.md` returns `0`

---

## Test Specification

Covered by the existing `tests/sdd_scripts/test_command_twin_parity.py`; the
grep-shaped criteria become permanent tests in TASK-3160.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 4, §1 Problem Statement)
2. **Check dependencies** — none. Record the parity baseline first:
   `pytest tests/sdd_scripts/test_command_twin_parity.py -q` → expect
   `1 failed, 1 passed`
3. **Verify the Codebase Contract** — re-confirm the line numbers; they were
   verified on 2026-09-11 and other FEAT-552 tasks do not touch this file
4. **Update status** in `sdd/tasks/index/worktree-creation-ownership.json` → `"in-progress"`
5. **Implement** from the blueprint
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3156-sdd-task-drops-worktree.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below — record the parity baseline you
   measured in step 2, so the FEAT-545 drift fix is attributable

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
