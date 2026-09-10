# TASK-3101: Path containment for `affected_paths`

**Feature**: FEAT-546 — Design Research Hardening
**Spec**: `sdd/specs/design-research-hardening.spec.md` (§3 Module 2)
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-545's own acceptance dry run found (S4, CONFIRM) that `/sdd-spec` §3b.4 verifies
each suggestion's `affected_paths` entries with a bare `test -e <path>` and no
containment check — an absolute path or a `../` traversal would be accepted
uncriticized. This task adds a containment check BEFORE the existing existence check,
with a distinct rejection reason so "not found" and "outside repository" stay
distinguishable in the triage output.

---

## Scope

- `.claude/commands/sdd-spec.md` §3b.4: insert a path-containment check before the
  existing `test -e <path>` verification instruction, with its own REJECT reason text.
- Mirror into `.agent/workflows/sdd-spec.md`.

**NOT in scope**: schema changes to `design_research.schema.json` (that would be S5,
explicitly deferred — non-goal); staging uniqueness (TASK-3100); execution record
(TASK-3102); MODIFY-block disambiguation (TASK-3103); probe validation (TASK-3104).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-spec.md` | MODIFY | §3b.4 prose, insert containment check + rejection wording |
| `.agent/workflows/sdd-spec.md` | MODIFY | Same edit (body parity) |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` at `416c7bc64` (2026-09-10). Re-grep heading text before editing.

### Anchors in `.claude/commands/sdd-spec.md` (574 lines)
```text
:308-317 #### 3b.4 Validate and triage (schema-validation python -c block)
:318-322 "For each suggestion (when not skipped): verify every `affected_paths` entry
         (`test -e <path>`); read the cited spots; decide **CONFIRM / REJECT /
         ESCALATE** with a one-sentence reason; write `$DR/triage.md` using the §9
         table shape from `sdd/templates/spec.md`. A suggestion with any unverifiable
         path is `REJECT — path not found`."                    ← REPLACE this paragraph
```
### Twin `.agent/workflows/sdd-spec.md` (578 lines)
```text
Same twin-parity contract as TASK-3100 — 4-line frontmatter + one `- Worktree policy:`
substitution line are the ONLY tolerated deltas
(`diff .agent/workflows/sdd-spec.md .claude/commands/sdd-spec.md | grep -c '^[<>]'` → `6`).
```
### `sdd/templates/design_research.schema.json` (31 lines) — READ ONLY reference, not modified
```json
"affected_paths": { "type": "array", "items": { "type": "string" }, "description": "Repo-relative paths the reviewer actually opened. Unverifiable paths cause the suggestion to be rejected." }
```

### Does NOT Exist
- ~~a path-containment/traversal check~~ in §3b.4 — today's check is `test -e <path>`
  only; this task adds the containment step BEFORE it
- ~~a schema change requiring absolute or repo-relative-only paths~~ — do NOT touch
  `design_research.schema.json` (non-goal, S5 deferred to a human decision)
- ~~`REJECT — path outside repository`~~ as rejection text — new wording added here,
  distinct from the existing `REJECT — path not found`

---

## Implementation Notes

### Pattern to Follow
`python -c` one-liners are already the established validation idiom in this exact
section (the schema-validation block immediately above, `:309-316`) — use the same
style for the containment check rather than inventing a new mechanism.

### Key Constraints
- Prefer a `python -c` realpath comparison over `readlink -f` (spec §7 Known Risks:
  `readlink -f` portability across shells/OSes).
- The check runs for EVERY `affected_paths` entry of EVERY suggestion, before the
  existing `test -e`; a path that fails containment must never reach `test -e` (so a
  crafted `../../../etc/passwd` is REJECTed as "outside repository", not silently
  found-or-not-found on the executing agent's actual filesystem).
- Never `exit` — this is per-suggestion triage prose, not a `SKIP_REASON` gate; a
  contained-check failure produces one REJECTed suggestion row, not a skipped phase.

---

## Implementation Blueprint

### Steps (in order)
1. Insert a containment-check instruction immediately before the existing "verify
   every `affected_paths` entry (`test -e <path>`)" sentence — *why*: containment must
   be checked before existence, so an out-of-repo path never reaches `test -e` (spec
   AC-4).
2. Add the new rejection wording alongside the existing one, keeping both distinct —
   *why*: "not found" and "outside repository" are different failure modes and must
   stay distinguishable in `triage.md`/spec §9 (spec AC-4).

### `.claude/commands/sdd-spec.md` (MODIFY — §3b.4, the paragraph at lines 318-322)
```markdown
# BEFORE (verified :318-322)
For each suggestion (when not skipped): verify every `affected_paths` entry
(`test -e <path>`); read the cited spots; decide **CONFIRM / REJECT /
ESCALATE** with a one-sentence reason; write `$DR/triage.md` using the §9
table shape from `sdd/templates/spec.md`. A suggestion with any unverifiable
path is `REJECT — path not found`.

# AFTER
For each suggestion (when not skipped), for every `affected_paths` entry:
1. **Containment check first**: resolve the path against `$REPO_ROOT` and confirm it
   stays inside it —
   ```bash
   python -c "
import os, sys
p = os.path.realpath(sys.argv[1])
root = os.path.realpath('$REPO_ROOT')
sys.exit(0 if p == root or p.startswith(root + os.sep) else 1)" "<path>" \
     || REASON="REJECT — path outside repository: <path>"
   ```
   A path that fails containment is `REJECT — path outside repository: <path>` and is
   NOT passed to `test -e` at all.
2. **Existence check** (only for paths that passed containment): `test -e <path>` —
   unverifiable ⇒ `REJECT — path not found: <path>`.
3. Read the cited spots for paths that pass both checks; decide **CONFIRM / REJECT /
   ESCALATE** with a one-sentence reason; write `$DR/triage.md` using the §9 table
   shape from `sdd/templates/spec.md`.
```
**Why this shape**: containment runs first and short-circuits `test -e` entirely for
an out-of-repo path, so the two rejection reasons never collide and a crafted
traversal path can never cause the executing agent to read outside the repository
(spec G2/AC-4). The `python -c` idiom matches the schema-validation block already in
this same sub-step, keeping the section internally consistent.

### FILL IN checklist
- [ ] none — the edit is fully specified; no judgement calls left open

---

## Acceptance Criteria

- [ ] `grep -n "path outside repository" .claude/commands/sdd-spec.md` → at least one match in §3b.4
- [ ] `grep -n "path not found" .claude/commands/sdd-spec.md` → still present, distinct wording from the above
- [ ] The containment check appears BEFORE the existence check in §3b.4's prose (verify by reading the section top-to-bottom)
- [ ] `diff .agent/workflows/sdd-spec.md .claude/commands/sdd-spec.md | grep -c '^[<>]'` → `6`
- [ ] `sdd/templates/design_research.schema.json` unchanged (`git diff` shows no hunks for this file) — spec AC-11
- [ ] No other file changed

---

## Test Specification

Manual (no dedicated Python test for this bash/prose section — spec §3 Module 6 covers
only the twin-parity check, which is existing and unaffected):
```bash
grep -n "path outside repository\|path not found" .claude/commands/sdd-spec.md
diff .agent/workflows/sdd-spec.md .claude/commands/sdd-spec.md | grep -c '^[<>]'   # expect 6
# Manual containment-check smoke test:
python -c "
import os, sys
p = os.path.realpath('../../etc/passwd')
root = os.path.realpath('.')
sys.exit(0 if p == root or p.startswith(root + os.sep) else 1)" && echo "BUG: accepted" || echo "correctly rejected"
```

---

## Agent Instructions

1. Read spec §3 Module 2 and §2 Overview/Component Diagram (G2).
2. Dependencies: none (parallel-safe with TASK-3100/3103/3104, but all four touch the
   same `sdd-spec.md`/`sdd-task.md` files — spec's Worktree Strategy recommends
   sequential in one worktree over parallel-worktree coordination).
3. Re-grep every anchor; implement from the blueprint; verify; commit both files.
4. Move to completed; index → `"done"`; Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
