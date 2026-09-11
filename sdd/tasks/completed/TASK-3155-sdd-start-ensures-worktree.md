# TASK-3155: `/sdd-start` provisions its own worktree

**Feature**: FEAT-552 — Worktree Creation Ownership
**Spec**: `sdd/specs/worktree-creation-ownership.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3154
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 — the hole that makes deferred creation possible. `/sdd-start`
today only *detects* whether it happens to be inside a worktree
(`.claude/commands/sdd-start.md:50`, "### 3. Detect Context") and shrugs if it
is not: *"If not, that's fine"*. Once TASK-3156 removes creation from
`/sdd-task`, that shrug becomes the bug: an operator who pulls task files on
another machine would implement straight onto `dev`.

This task turns detection into provisioning.

---

## Scope

- Replace `### 3. Detect Context` in `.claude/commands/sdd-start.md` with
  `### 3. Ensure the Worktree`, which resolves the flow from the per-spec index
  header and calls `python -m scripts.sdd.ensure_worktree`.
- Mirror the identical edit into the twin `.agent/workflows/sdd-start.md`.

**NOT in scope**: renumbering any other section (§3 stays §3); touching
`/sdd-task` (TASK-3156), `sdd-worker` (TASK-3157) or `CLAUDE.md` (TASK-3159).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-start.md` | MODIFY | §3 Detect Context → Ensure the Worktree |
| `.agent/workflows/sdd-start.md` | MODIFY | Same edit, keeping the twin in sync |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```bash
# The CLI this section calls — created by TASK-3154
python -m scripts.sdd.ensure_worktree --slug <slug> --feature-id FEAT-<NNN> \
  --spec <spec-path> --index sdd/tasks/index/<slug>.json
```

### Existing Signatures to Use
```
.claude/commands/sdd-start.md
  line 13  ## Guardrails  (mentions FEAT-145 worktree/index co-location)
  line 23  ### 1. Resolve the Task   — resolves INDEX, feature_id, feature slug, spec
  line 38  ### 2. Validate Readiness
  line 50  ### 3. Detect Context     <-- the section this task replaces
  line 65  ### 4. Mark In-Progress (in place)
```
`### 3. Detect Context` occurs exactly once
(verified: `grep -c '### 3. Detect Context' .claude/commands/sdd-start.md` → 1)
and once in the twin at `.agent/workflows/sdd-start.md:54`.

The per-spec index header carries everything the section needs — no spec
frontmatter parsing required (verified: `sdd/tasks/index/token-budget-bedrock.json`):
```json
{"feature": "token-budget-bedrock", "feature_id": "FEAT-550",
 "spec": "sdd/specs/token-budget-bedrock.spec.md",
 "type": "feature", "base_branch": "dev"}
```

### Does NOT Exist
- ~~a parity test covering `sdd-start`~~ — `tests/sdd_scripts/test_command_twin_parity.py`
  has `_TWINNED = ("sdd-spec", "sdd-task")` (line 21), so `sdd-start`'s twin is
  NOT machine-checked. Update it anyway: nothing will catch you if you forget.
- ~~`.claude/commands/sdd-start.md` frontmatter~~ — the file starts directly with
  `# /sdd-start — Start an SDD Task`; only the `.agent/workflows/` twin carries
  a `description:` block (lines 1-3). Do not add one.
- ~~`/sdd-start` creating a branch by hand~~ — it must not contain a
  `git worktree add`; the CLI owns that

---

## Implementation Notes

### Key Constraints
- `/sdd-start` is very often invoked *already inside* the target worktree. The
  CLI treats that as reuse and prints the same path, so the section must not
  add its own "am I in a worktree?" branching — just call it and `cd`.
- On a non-zero exit, STOP. Never fall back to implementing on `base_branch`;
  that is the failure this feature exists to prevent.
- Keep the FEAT-145 paragraph about per-spec indexes — it is still true and
  explains why committing from the worktree is safe.

### References in Codebase
- `.claude/agents/sdd-worker.md:183-199` — the sibling section TASK-3157 rewrites
  the same way; keep the two readable as a pair

---

## Implementation Blueprint

### Steps (in order)
1. Replace the section in `.claude/commands/sdd-start.md` — *why*: it is the
   interactive lane's only entry point, and the one with no provisioning today.
2. Apply the byte-identical replacement to `.agent/workflows/sdd-start.md` —
   *why*: the twin is what the workflow lane reads; untested drift is still drift.
3. Re-run the twin parity suite — *why*: to confirm you did not disturb the
   `sdd-spec`/`sdd-task` pairs it does check.

### `.claude/commands/sdd-start.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '### 3. Detect Context' .claude/commands/sdd-start.md)
# REPLACE — the whole section from `### 3. Detect Context` (verified: .claude/commands/sdd-start.md:50)
#           up to, but NOT including, `### 4. Mark In-Progress (in place)` (line 65)

### 3. Ensure the Worktree

The worktree is created by whoever is about to write code in it — not at
planning time (FEAT-552). `/sdd-task` no longer creates one, so this step
provisions it, idempotently: already inside the right worktree, it is a no-op
that prints the path you are already in.

Everything the step needs is in the per-spec index header resolved in §1
(`feature_id`, `feature`, `spec`, `type`, `base_branch`):

(as a fenced `bash` block in the final file):

    WT=$(python -m scripts.sdd.ensure_worktree \
           --slug "<feature-slug>" \
           --feature-id "<FEAT-ID>" \
           --spec "<spec-path>" \
           --index "sdd/tasks/index/<feature-slug>.json")
    cd "$WT"

For a hotfix (`type: hotfix` in the index header) pass `--jira-key <KEY>`
instead of `--feature-id`; the CLI applies the FEAT-466 naming and branches
from `origin/main`.

If the command exits non-zero, **STOP** and show its message verbatim. Do NOT
fall back to implementing on `<base_branch>` — an un-isolated implementation is
exactly what this step exists to prevent. The two messages you are most likely
to see are a leftover branch with no worktree, and task artifacts missing from
the base you branched off (fetch and re-run).

With per-spec indexes (FEAT-145), commits then land in the worktree's own
branch. Each feature owns its own index file, so parallel worktrees never
collide on shared mutable state.
```
**Why this shape**: the FEAT-145 paragraph survives, moved below the provisioning
so the section reads as "get the worktree, then know why committing here is
safe". The hotfix line is one sentence because `plan_worktree` owns the rule —
this file must never restate the naming template. The explicit "do NOT fall
back" is load-bearing: an agent that silently continues on `dev` reproduces the
pre-FEAT-552 damage.

### `.agent/workflows/sdd-start.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '### 3. Detect Context' .agent/workflows/sdd-start.md)
# REPLACE — same section, same replacement text, at .agent/workflows/sdd-start.md:54
# (the twin differs from the original ONLY by its leading `description:` frontmatter,
#  lines 1-3 — do not copy the frontmatter away, and do not add one to the original)
```
**Why**: `.agent/workflows/` is the copy the workflow lane loads. It is not
covered by `test_command_twin_parity.py` (`_TWINNED` lists only `sdd-spec` and
`sdd-task`), so this is a discipline step, not a test-driven one.

### FILL IN checklist
- [ ] none — this task's blueprint is complete markdown; apply it verbatim to both files

---

## Acceptance Criteria

- [ ] `.claude/commands/sdd-start.md` contains `### 3. Ensure the Worktree` and no `### 3. Detect Context`
- [ ] The section invokes `python -m scripts.sdd.ensure_worktree` and `cd`s to its output
- [ ] `grep -c "git worktree add" .claude/commands/sdd-start.md` returns `0`
- [ ] Section numbering is unchanged elsewhere: §1, §2, §3, §4 … §9 each appear exactly once
- [ ] `.agent/workflows/sdd-start.md` carries the same section, still with its `description:` frontmatter intact
- [ ] `pytest tests/sdd_scripts/test_command_twin_parity.py -q` is no worse than the baseline recorded in TASK-3156 (`sdd-spec` passes)
- [ ] The command still reads `type`/`base_branch` from the per-spec index header, not from spec frontmatter

---

## Test Specification

No Python module changes. Verification is the grep-shaped criteria above;
TASK-3160 turns the durable ones into `tests/sdd_scripts/test_command_contracts.py`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 3)
2. **Check dependencies** — TASK-3154 must be in `sdd/tasks/completed/`, and
   `python -m scripts.sdd.ensure_worktree --help` must exit 0 before you point
   a command at it
3. **Verify the Codebase Contract** — re-confirm the `### 3. Detect Context`
   anchor and the line of `### 4. Mark In-Progress (in place)` in both files
4. **Update status** in `sdd/tasks/index/worktree-creation-ownership.json` → `"in-progress"`
5. **Implement** — apply the blueprint to both files
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3155-sdd-start-ensures-worktree.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (fallback — the parrot-sdd-coder codex-spark
attempt failed instantly on a CLI argument mismatch, `--ask-for-approval`;
the qwen/nova retry then timed out after ~9 minutes)
**Date**: 2026-09-11
**Notes**: Replaced `### 3. Detect Context` with `### 3. Ensure the
Worktree` in `.claude/commands/sdd-start.md`, applying the blueprint text
verbatim, and mirrored the identical edit into `.agent/workflows/sdd-start.md`
(preserving its `description:` frontmatter). Verified all 7 acceptance
criteria: the new heading exists and the old one is gone, the section
invokes `python -m scripts.sdd.ensure_worktree` and `cd`s to `$WT`, no
`git worktree add` remains, §1-§9 headings are each present exactly once
and unrenumbered, the twin carries the same section with its frontmatter
intact, `pytest tests/sdd_scripts/test_command_twin_parity.py -q` still
reports `2 passed` (no worse than the TASK-3156 baseline), and the section
reads `type`/`base_branch` from the per-spec index header, not spec
frontmatter.

**Deviations from spec**: none

Seat: sdd-worker (sonnet, direct) · Backend: n/a (fallback after two MCP-seat
failures) · Model: claude-sonnet-5 · Attempts: 3 (codex-spark CLI-arg error
1.08s, qwen/nova timeout 551.89s, direct fallback success) · Duration: n/a
(fallback) · Tokens: n/a
