# TASK-3103: Disambiguate MODIFY blueprint blocks

**Feature**: FEAT-546 — Design Research Hardening
**Spec**: `sdd/specs/design-research-hardening.spec.md` (§3 Module 4)
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-545's own acceptance dry run found (S8, CONFIRM) that a task-template MODIFY
block only says "insert below `<anchor>`" with no rule about what happens if the
anchor text occurs more than once in the target file — a non-thinking executor could
duplicate an insertion. This task adds a required occurrence-count line to the MODIFY
example and a written disambiguation rule to `/sdd-task`'s blueprint rules — no
automated lint (that would be S9, explicitly deferred/ESCALATE in FEAT-545 §9).

---

## Scope

- `sdd/templates/task.md`: MODIFY example gains a `# occurrences: <N>` line.
- `.claude/commands/sdd-task.md` §3 blueprint rules: add the disambiguation sub-rule.
- Mirror the `sdd-task.md` edit into `.agent/workflows/sdd-task.md`.

**NOT in scope**: an automated occurrence-count linter (S9, deferred — human decision);
staging/path/record/probe changes (TASK-3100/3101/3102/3104); tests (TASK-3105).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/templates/task.md` | MODIFY | MODIFY example gains one new line |
| `.claude/commands/sdd-task.md` | MODIFY | Rule 1 of the blueprint block gains a disambiguation sub-clause |
| `.agent/workflows/sdd-task.md` | MODIFY | Same edit (body parity) |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` at `416c7bc64` (2026-09-10). Re-grep heading text before editing.

### Anchors in `sdd/templates/task.md` (220 lines)
```text
:130-135 ### `parrot/path/to/existing.py` (MODIFY)
  :131   ```python
  :132   # AFTER — insert below `<verbatim anchor line>` (verified: parrot/path/to/existing.py:NN)
  :133   <new lines>
  :134   ```
  :135   **Why**: <1–2 sentences>                                ← insert the new occurrences line into the fenced block, before line 132's comment, or as its own line immediately after it
```
### Anchors in `.claude/commands/sdd-task.md` (328 lines)
```text
:116-118 CRITICAL — Implementation Blueprint per Task, rule 1:
  "1. **One block per file** listed in \"Files to Create / Modify\" — CREATE blocks
      are whole-file starting points; MODIFY blocks quote the verified anchor line
      they attach to (`# AFTER — insert below \`<anchor>\` (verified: path:NN)`)."   ← APPEND a sub-clause to this rule
```
### Twin `.agent/workflows/sdd-task.md` (332 lines)
```text
Twin-parity contract (verified, re-checked post-FEAT-545): the ONLY tolerated deltas
are the 4-line frontmatter and the
"(sub-features extend a parent feature branch — see `AGENTS.md`)." substitution line
(NOT a "- Worktree policy:" line — that pattern belongs to `sdd-spec.md`'s twin only;
`sdd-task.md`'s twin has no such line at all — this was a documented correction from
FEAT-545 TASK-3094's own Completion Note, re-verify it still holds before assuming).
`diff .agent/workflows/sdd-task.md .claude/commands/sdd-task.md | grep -c '^[<>]'` → `6` today.
```

### Does NOT Exist
- ~~`# occurrences:`~~ anywhere in `sdd/templates/task.md` or `.claude/commands/sdd-task.md` — new text added by this task
- ~~an automated MODIFY-anchor-occurrence linter~~ (e.g. a `scripts/sdd/lint_new.py`
  addition) — explicitly NOT created; this is S9 in FEAT-545 §9, disposed ESCALATE
  (human decision), out of scope here
- ~~a change to the CREATE block example~~ — this task touches the MODIFY example only

---

## Implementation Notes

### Pattern to Follow
Mirror the tone of the existing blueprint rules (`.claude/commands/sdd-task.md:96-144`):
a numbered rule, imperative + reason, consistent with FEAT-545's own "Explain-for-executor
rule" (rule 7 of the same block).

### Key Constraints
- The occurrence count must be **verified by the task-writing agent** (`grep -c
  '<anchor>' path/to/existing.py`), not assumed — same anti-hallucination bar as every
  other anchor in this repo's SDD tooling.
- When occurrence count is `1`, the MODIFY block proceeds exactly as before (no change
  in behavior) — this task only adds behavior for the `> 1` case.

---

## Implementation Blueprint

### Steps (in order)
1. Add the occurrence-count line to `task.md`'s MODIFY example — *why*: shows future
   task authors the exact shape (spec AC-7).
2. Add the disambiguation sub-clause to `sdd-task.md`'s rule 1 — *why*: tells the
   task-writing agent what to do when the count is `> 1` (spec AC-7).
3. Regenerate the `sdd-task.md` twin and confirm `diff | grep -c '^[<>]'` → `6`.

### `sdd/templates/task.md` (MODIFY — insert into the MODIFY example fenced block)
```markdown
# BEFORE (verified :130-135)
### `parrot/path/to/existing.py` (MODIFY)
```python
# AFTER — insert below `<verbatim anchor line>` (verified: parrot/path/to/existing.py:NN)
<new lines>
```
**Why**: <1–2 sentences>

# AFTER
### `parrot/path/to/existing.py` (MODIFY)
```python
# occurrences: <N> (verified: grep -c '<verbatim anchor line>' parrot/path/to/existing.py)
# AFTER — insert below `<verbatim anchor line>` (verified: parrot/path/to/existing.py:NN)
<new lines>
```
**Why**: <1–2 sentences>. If `<N>` > 1: replace the block above with
`# FILL IN: disambiguate — quote enough surrounding context (2–3 lines) to make the
anchor unique` instead of a bare one-line anchor.
```
**Why this shape**: the `# occurrences:` line forces the task-writing agent to
actually run `grep -c` before committing to a one-line anchor, and the inline
fallback instruction shows exactly what to do instead when that count is `> 1` —
mirroring the existing `# FILL IN: <decision> — bounded by <constraint | AC-N>`
convention already used elsewhere in this same template (spec G4).

### `.claude/commands/sdd-task.md` (MODIFY — append to rule 1 of the Implementation Blueprint block)
```markdown
# BEFORE (verified :116-118)
1. **One block per file** listed in "Files to Create / Modify" — CREATE blocks
   are whole-file starting points; MODIFY blocks quote the verified anchor line
   they attach to (`# AFTER — insert below \`<anchor>\` (verified: path:NN)`).
# AFTER
1. **One block per file** listed in "Files to Create / Modify" — CREATE blocks
   are whole-file starting points; MODIFY blocks quote the verified anchor line
   they attach to (`# AFTER — insert below \`<anchor>\` (verified: path:NN)`).
   **MODIFY blocks MUST state the anchor's occurrence count**
   (`# occurrences: <N> (verified: grep -c '<anchor>' path)`); if `<N>` is `> 1`,
   the block is `# FILL IN: disambiguate — quote enough surrounding context (2–3
   lines) to make the anchor unique` instead of a bare one-line anchor.
```
**Why**: makes the occurrence-count check a per-task quality-bar item, not just
template decoration — the existing "Quality bar" paragraph right after this rule
block already treats a missing blueprint as incomplete; this sub-clause extends that
bar to an ambiguous MODIFY anchor (spec G4/AC-7).

### `.agent/workflows/sdd-task.md` (MODIFY — regenerate body)
```bash
head -n 4 .agent/workflows/sdd-task.md > /tmp/twin.md
cat .claude/commands/sdd-task.md | \
  sed 's|(sub-features extend a parent feature branch — see `CLAUDE.md`)\.|(sub-features extend a parent feature branch — see `AGENTS.md`).|' >> /tmp/twin.md
mv /tmp/twin.md .agent/workflows/sdd-task.md
diff .agent/workflows/sdd-task.md .claude/commands/sdd-task.md | grep -c '^[<>]'   # expect 6
```
**Why**: exact recipe FEAT-545's TASK-3094 used and documented as correct for this
twin (its Completion Note explicitly corrected the earlier, wrong "Worktree policy"
assumption) — reuse it verbatim rather than re-deriving.

### FILL IN checklist
- [ ] none — both edits are fully specified; no judgement calls left open

---

## Acceptance Criteria

- [ ] `grep -c "# occurrences:" sdd/templates/task.md` → `1`
- [ ] `grep -n "MODIFY blocks MUST state the anchor's occurrence count" .claude/commands/sdd-task.md` → one match
- [ ] `grep -n "FILL IN: disambiguate" sdd/templates/task.md .claude/commands/sdd-task.md` → at least one match in each file
- [ ] `diff .agent/workflows/sdd-task.md .claude/commands/sdd-task.md | grep -c '^[<>]'` → `6`
- [ ] No other file changed

---

## Test Specification

Automated: `tests/sdd_scripts/test_design_research_templates.py`'s
`test_task_template_modify_block_states_occurrence_count` (added by TASK-3105) asserts
`"# occurrences:" in task.md`. Manual now:
```bash
grep -n "# occurrences:" sdd/templates/task.md
grep -n "MODIFY blocks MUST state the anchor's occurrence count" .claude/commands/sdd-task.md
diff .agent/workflows/sdd-task.md .claude/commands/sdd-task.md | grep -c '^[<>]'   # expect 6
```

---

## Agent Instructions

1. Read spec §3 Module 4.
2. Dependencies: none (parallel-safe with TASK-3100/3101/3104, but all touch
   `sdd-spec.md`/`sdd-task.md`/`task.md` — spec's Worktree Strategy recommends
   sequential in one worktree).
3. Re-grep every anchor; implement from the blueprint; verify; commit all three files.
4. Move to completed; index → `"done"`; Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-10
**Notes**: Implemented exactly per blueprint. `sdd/templates/task.md`'s
MODIFY example now leads with `# occurrences: <N> (verified: grep -c
'<verbatim anchor line>' parrot/path/to/existing.py)` and the **Why**
paragraph documents the `> 1` disambiguation fallback. `.claude/commands/
sdd-task.md` rule 1 of the Implementation Blueprint block gained the
matching sub-clause. Twin regenerated with the established recipe; both
`test_command_twin_parity` cases pass (`diff | grep -c '^[<>]'` → `6`).
**Deviations from spec**: none
