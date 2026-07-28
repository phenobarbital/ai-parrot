# TASK-1966: Wire `/sdd-task` and `/sdd-spec` to `reserve_ids.py`

**Feature**: FEAT-387 — SDD Task-ID Allocation Race Fix
**Spec**: `sdd/specs/sdd-task-id-allocation-race.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1964
**Assigned-to**: unassigned

---

## Context

TASK-1964 produces a working, tested `reserve_ids.py` allocator. This task
implements spec §3 Module 4: replace the undocumented "scan existing files,
take the max, increment" numbering steps in the two SDD command
DEFINITIONS (`.claude/commands/sdd-task.md` and
`.claude/commands/sdd-spec.md`) with explicit instructions to call
`reserve_ids.py` and use its output verbatim. These are markdown command
definitions consumed by Claude Code sessions (not Python source) — this
task edits *documentation/instructions*, not application code, but is
still the piece that actually closes the loop end-to-end for real
`/sdd-task`/`/sdd-spec` invocations.

---

## Scope

- In `.claude/commands/sdd-task.md` §4 "Generate Tasks": replace step 3
  ("For each task, create `sdd/tasks/active/TASK-<NNN>-<slug>.md`...")
  with an explicit instruction to run
  `python -m scripts.sdd.reserve_ids --kind task --count <N> --base-branch
  <BASE> --label <feature-slug>` FIRST (where `<N>` is the total number of
  tasks about to be generated), capture the printed `TASK-<NNN>` list, and
  use those IDs — in order — for the task files about to be created.
- In `.claude/commands/sdd-spec.md`, replace "Feature ID (check existing;
  increment last; start at FEAT-001 if none)" (line 230) with: call
  `python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch
  <BASE> --label <feature-slug>` and use the returned `FEAT-<NNN>` — UNLESS
  the spec is an intentional, explicit split of an existing initiative
  across multiple specs (the FEAT-380-style pattern), in which case the
  author states the FEAT-ID to reuse explicitly (documented escape hatch;
  spec §8 Open Question — implement as a frontmatter field
  `reuse_feature_id: FEAT-<NNN>` that, when present, skips the
  reservation call entirely and uses the stated ID).
- Update both commands' guardrail bullet lists to state the new behavior
  plainly (e.g. `/sdd-task`'s current guardrail "Check `sdd/tasks/index/
  <feature>.json` for existing tasks to avoid duplication" stays, but a
  new guardrail is added stating IDs are reserved via `reserve_ids.py`,
  never hand-computed).
- Do NOT touch any other section of either command file (worktree
  creation, commit steps, output format, etc. are unchanged).

**NOT in scope**:
- The allocator implementation itself (TASK-1964, already done by the time
  this task starts).
- CI wiring / docs in `sdd/WORKFLOW.md` / `CLAUDE.md` (TASK-1967).
- Any change to `/sdd-start`, `/sdd-done`, or any other command.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-task.md` | MODIFY | §4 "Generate Tasks" numbering step now calls `reserve_ids.py` |
| `.claude/commands/sdd-spec.md` | MODIFY | Feature-ID assignment step now calls `reserve_ids.py`, with an explicit-reuse escape hatch |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` HEAD on 2026-07-28. TASK-1964 (this task's
> dependency) must be `done` before starting — re-verify the CLI's exact
> flag names/output format against its actual implementation before
> writing the new command instructions, since the executing agent for
> TASK-1964 may have adjusted details within its own scope.

### Verified Imports
N/A — this task edits markdown command-definition files, not Python
source. No imports to verify.

### Existing Signatures to Use
```markdown
<!-- .claude/commands/sdd-task.md:94-97 (current numbering step to replace) -->
### 4. Generate Tasks
1. Ensure `sdd/tasks/active/` directory exists (create if needed).
2. Read the task template at `sdd/templates/task.md`.
3. For each task, create `sdd/tasks/active/TASK-<NNN>-<slug>.md` using the template.

<!-- .claude/commands/sdd-spec.md:230 (current Feature-ID assignment line to replace) -->
   - Feature ID (check existing; increment last; start at FEAT-001 if none).
```

**CLI contract to depend on** (produced by TASK-1964 — re-verify exact flag
names/behavior by reading `scripts/sdd/reserve_ids.py` before writing the
new command steps, do not assume the sketch below is final):
```
python -m scripts.sdd.reserve_ids --kind task --count <N> --base-branch <BASE> --label <slug>
# prints one TASK-<NNN> per line on success, exit 0
# raises IdReservationError / non-zero exit after max_retries on failure
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `/sdd-task` §4 | `scripts/sdd/reserve_ids.py` CLI | shell command inside the markdown instructions | `.claude/commands/sdd-task.md:94-97` |
| `/sdd-spec` Feature-ID step | `scripts/sdd/reserve_ids.py` CLI | shell command inside the markdown instructions | `.claude/commands/sdd-spec.md:230` |

### Does NOT Exist
- ~~A `--dry-run` flag on `reserve_ids.py`~~ — verify whether TASK-1964
  actually implemented one before referencing it; the spec's Module 2
  description does not require it, and this task must not invent a flag
  that doesn't exist in the real CLI.
- ~~Any existing `reuse_feature_id` frontmatter field~~ — this task
  introduces it for the first time; it is not read by any other command
  today (confirm via `grep -rn "reuse_feature_id"` before assuming
  otherwise).

---

## Implementation Notes

### Pattern to Follow
Mirror the existing style of embedded shell snippets already present in
both command files (e.g. `.claude/commands/sdd-task.md:173-188`'s
"Commit Tasks and Per-Spec Index" bash block) — a fenced ` ```bash ` block
with the exact command, followed by prose explaining what to do with its
output. Keep the same terse, imperative instructional voice used
throughout both files.

### Key Constraints
- The reservation call MUST happen before any task/spec file is written,
  so a failed reservation (network error, exhausted retries) aborts
  cleanly with nothing left half-created.
- Do not change the per-spec index schema, the task template, or the
  commit conventions documented in either file — only the ID-numbering
  step itself.
- Preserve every existing guardrail bullet; only ADD the new one about
  reservation (per Scope above) — do not delete "Feature IDs must be
  unique. Check existing specs before assigning." from `/sdd-spec`'s
  guardrails outright; rephrase it to reflect that uniqueness is now
  enforced by the reservation mechanism rather than manual checking.

### References in Codebase
- `.claude/commands/sdd-task.md` — full file, especially §1 (base-branch
  sync, already establishes the pattern of reading `sdd_meta.parse()`
  output into shell variables) and §4/§5 (numbering + commit steps this
  task modifies).
- `.claude/commands/sdd-spec.md` — full file, especially the Feature-ID
  assignment line and surrounding guardrails.

---

## Acceptance Criteria

- [ ] `.claude/commands/sdd-task.md` §4 instructs the reader to call
      `reserve_ids.py` for the total task count and use its output
      verbatim for `TASK-<NNN>` file names and index entries.
- [ ] `.claude/commands/sdd-spec.md` instructs the reader to call
      `reserve_ids.py` for a new `FEAT-<NNN>`, with a documented
      `reuse_feature_id` frontmatter escape hatch for intentional splits.
- [ ] Neither file's other sections (worktree creation, commit steps,
      output format, per-spec index schema) changed.
- [ ] No linting errors on any Python touched (none expected — this task
      is markdown-only, but run `ruff check .` anyway to confirm no
      accidental Python edits crept in).

---

## Test Specification

This task edits Claude Code command DEFINITIONS (markdown instructions
consumed by an LLM session), not executable Python — there is no
`pytest`-style test scaffold. Verification is manual/textual:

```bash
# Confirm the old ad-hoc numbering language is gone:
grep -n "increment last" .claude/commands/sdd-spec.md   # expect: no match
grep -n "For each task, create" .claude/commands/sdd-task.md  # expect: rewritten to reference reserve_ids.py

# Confirm the new call is present:
grep -n "reserve_ids" .claude/commands/sdd-task.md .claude/commands/sdd-spec.md  # expect: matches in both
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sdd-task-id-allocation-race.spec.md` for full context.
2. **Check dependencies** — verify TASK-1964 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `scripts/sdd/reserve_ids.py`'s actual CLI interface (flags, output format, exit codes) before writing the new command instructions.
4. **Update status** in `sdd/tasks/index/sdd-task-id-allocation-race.json` → `"in-progress"`.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-1966-wire-sdd-task-sdd-spec-to-allocator.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
