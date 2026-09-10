# TASK-3100: Unique, atomic research staging

**Feature**: FEAT-546 — Design Research Hardening
**Spec**: `sdd/specs/design-research-hardening.spec.md` (§3 Module 1)
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-545's own acceptance dry run found (S2, CONFIRM in its spec §9) that `/sdd-spec`
§3b's staging directory is a deterministic, reusable path with no per-run uniqueness,
and its promotion into `sdd/state/<FEAT-ID>/design_research/` is a bare `mkdir -p` +
wildcard `mv` with no cleanup-on-failure. This task makes staging run-scoped and its
promotion atomic.

---

## Scope

- `.claude/commands/sdd-spec.md` §3b.1: make `DR=` per-run-unique.
- `.claude/commands/sdd-spec.md` §6: make the promotion atomic (stage under a temp
  name inside `sdd/state/<FEAT-ID>/`, `mv` into place in one step only on full success;
  on failure, leave `$DR` untouched under `sdd/state/.design_research/`).
- Mirror both edits into `.agent/workflows/sdd-spec.md`.

**NOT in scope**: path containment (TASK-3101); execution record (TASK-3102, depends
on this task's `$DR`); MODIFY-block disambiguation (TASK-3103); probe validation
(TASK-3104); tests (TASK-3105).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-spec.md` | MODIFY | §3b.1 `DR=` line; §6 promotion block |
| `.agent/workflows/sdd-spec.md` | MODIFY | Same 2 edits (body parity) |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` at `416c7bc64` (2026-09-10, after FEAT-545 merged at `f98a14f26`).
> Re-grep heading text before editing — line numbers shift, heading text does not.

### Anchors in `.claude/commands/sdd-spec.md` (574 lines)
```text
:238-250 #### 3b.1 Detect and probe
:239     REPO_ROOT="$(pwd)"
:240     MODEL="${SDD_DESIGN_RESEARCH_MODEL:-gpt-5.6-luna}"
:241     DR="sdd/state/.design_research/<feature-name>"      ← REPLACE this line
:242     mkdir -p "$DR"; SKIP_REASON=""
:487-517 ### 6. Commit the Spec
:497-517 fenced bash: git reset HEAD / git add sdd/specs/... / promotion if-block / git diff --cached / git commit
:503-508 if [ -d "sdd/state/.design_research/<feature-name>" ]; then
             mkdir -p "sdd/state/<FEAT-ID>/design_research"
             mv sdd/state/.design_research/<feature-name>/* "sdd/state/<FEAT-ID>/design_research/"
             rmdir "sdd/state/.design_research/<feature-name>"
             git add "sdd/state/<FEAT-ID>/design_research/"
         fi                                                    ← REPLACE this block
```
### Twin `.agent/workflows/sdd-spec.md` (578 lines)
```text
:1-4  frontmatter (keep, twin-only)
:558  "- Worktree policy: `AGENTS.md` and `sdd/WORKFLOW.md`"    ← keep; original (.claude/commands/sdd-spec.md) says `CLAUDE.md` (section "Worktree Policy")
```
The only tolerated deltas are the 4-line frontmatter and this one substitution line
(verified: `diff .agent/workflows/sdd-spec.md .claude/commands/sdd-spec.md | grep -c
'^[<>]'` → `6` today — 4 frontmatter + 1 changed line pair). This task's edits must
land IDENTICALLY in both files outside that one tolerated line.

### Does NOT Exist
- ~~a run-id / timestamp / PID component in `$DR`~~ — not present yet; this task adds it
- ~~atomic promotion (temp-name-then-rename)~~ in §6 — today's promotion is a bare
  `mkdir -p` + wildcard `mv`, not atomic; this task makes it atomic
- ~~`uuid` module or dependency~~ — do NOT add one; `date` + `$$` (already-used shell
  primitives) are sufficient per spec §7 Known Risks/Gotchas

---

## Implementation Notes

### Pattern to Follow
FEAT-545's own precedent for editing this exact command (`TASK-3097`'s blueprint):
quote the verbatim BEFORE line(s), show the AFTER text, one `**Why**` paragraph per
edit.

### Key Constraints
- Never introduce a Python helper module (spec Non-Goal, same as FEAT-545's S1
  rejection) — this stays bash inside the command.
- The run-id must be filesystem-safe (no `:` — UTC `date` with `%Y%m%dT%H%M%SZ`
  format avoids colons) and human-scannable in a failure message.
- Do not change the FINAL committed path `sdd/state/<FEAT-ID>/design_research/` —
  spec §8 already resolved that it stays unkeyed; only the STAGING path and the
  promotion mechanism change.

---

## Implementation Blueprint

### Steps (in order)
1. Replace §3b.1's `DR=` line to append a run-id suffix — *why*: makes concurrent or
   rerun invocations for the same feature name collision-free (spec AC-2).
2. Replace §6's promotion if-block with a stage-then-atomic-rename sequence — *why*:
   a fault mid-copy must not leave a partially-populated destination (spec AC-3).
3. Regenerate the twin and confirm `diff | grep -c '^[<>]'` → `6` — *why*: G6/AC-8.

### `.claude/commands/sdd-spec.md` (MODIFY — §3b.1, line 241)
```bash
# BEFORE (verified :241)
DR="sdd/state/.design_research/<feature-name>"      # id-independent staging: FEAT-ID is reserved only in §5
# AFTER
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
DR="sdd/state/.design_research/<feature-name>-${RUN_ID}"   # id-independent, run-scoped staging: FEAT-ID is reserved only in §5
```
**Why**: a timestamp + PID suffix makes `$DR` unique per invocation, so a rerun or a
concurrent `/sdd-spec` call for the same feature name can never read or promote a
stale/foreign run's `suggestions.json` (spec S2/AC-2).

### `.claude/commands/sdd-spec.md` (MODIFY — §6, lines 503-508)
```bash
# BEFORE (verified :503-508)
if [ -d "sdd/state/.design_research/<feature-name>" ]; then
  mkdir -p "sdd/state/<FEAT-ID>/design_research"
  mv sdd/state/.design_research/<feature-name>/* "sdd/state/<FEAT-ID>/design_research/"
  rmdir "sdd/state/.design_research/<feature-name>"
  git add "sdd/state/<FEAT-ID>/design_research/"
fi
# AFTER
if [ -d "$DR" ]; then
  STAGE_TMP="sdd/state/.design_research/.promote-<FEAT-ID>-${RUN_ID}"
  mkdir -p "$STAGE_TMP" && cp -a "$DR"/. "$STAGE_TMP"/ \
    && mv "$STAGE_TMP" "sdd/state/<FEAT-ID>/design_research" \
    && rm -rf "$DR" \
    && git add "sdd/state/<FEAT-ID>/design_research/" \
    || { echo "⚠️  Promotion of $DR failed — left in place for inspection (run-id ${RUN_ID})." ; rm -rf "$STAGE_TMP"; }
fi
```
**Why this shape**: `cp -a` into a temp directory inside the FINAL parent
(`sdd/state/<FEAT-ID>/`), then a single `mv` to the real name, means the destination
`design_research/` either appears complete in one filesystem operation or not at all —
no window where it exists half-populated. On any failure the run-scoped `$DR` (still
gitignored, still on disk) is left for manual inspection instead of silently
half-promoted (spec AC-3); `FEAT-<ID>` and `<feature-name>` are the same literal
placeholders `/sdd-spec` already substitutes elsewhere in this section.

### FILL IN checklist
- [ ] none — both edits are fully specified; no judgement calls left open

---

## Acceptance Criteria

- [ ] `grep -n 'RUN_ID="\$(date' .claude/commands/sdd-spec.md` → one match in §3b.1
- [ ] `grep -n 'STAGE_TMP=' .claude/commands/sdd-spec.md` → one match in §6
- [ ] Two invocations of the §3b.1 `DR=`/`RUN_ID=` lines 1+ second apart (or with
  different `$$`) produce different `$DR` values — verify by sourcing the block twice
  in a throwaway shell with `sleep 1` between, or by noting differing `$$` alone
  suffices within the same second
- [ ] `diff .agent/workflows/sdd-spec.md .claude/commands/sdd-spec.md | grep -c '^[<>]'` → `6`
- [ ] No other file changed (`git status` shows only the two command files)

---

## Test Specification

Manual (this feature has no dedicated Python test for bash execution semantics — spec
§3 Module 6 relies on the existing `test_command_twin_parity.py`):
```bash
grep -n 'RUN_ID=\|STAGE_TMP=' .claude/commands/sdd-spec.md
diff .agent/workflows/sdd-spec.md .claude/commands/sdd-spec.md | grep -c '^[<>]'   # expect 6
```

---

## Agent Instructions

1. Read spec §3 Module 1 and §2 Overview/Component Diagram (G1).
2. Dependencies: none.
3. Re-grep every anchor in the Codebase Contract before editing.
4. Update status in `sdd/tasks/index/design-research-hardening.json` → `"in-progress"`.
5. Implement from the blueprint above.
6. Verify acceptance criteria; commit both files together.
7. Move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
