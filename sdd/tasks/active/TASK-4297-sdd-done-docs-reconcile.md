# TASK-4297: Document the reconciling export in `/sdd-done` §9.1 and the cheatsheet

**Feature**: FEAT-671 — Reconciling Ledger Snapshot Export
**Spec**: `sdd/specs/commands-sdd-done-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:62038221413a`

---

## Context

Spec §3 Module 3. The `/sdd-done` step 9.1 prose (twins `.claude/commands/sdd-done.md:412-417`
and `.agent/workflows/sdd-done.md:306-311`) still describes the export as a plain regeneration.
Operators need to read the new invariant where the step is documented, and the cheatsheet must
mention the `--no-reconcile` opt-out that TASK-4296 adds. The flag name is fixed by the spec, so
this task does not wait on the code tasks.

---

## Scope

- Insert one identical paragraph after the §9.1 intro paragraph in BOTH `/sdd-done` twins.
- Append `[--no-reconcile]` to the `ledger export` mention in `docs/wiki/cheatsheet.md:253`.

**NOT in scope**: the §9.1 bash block (must stay byte-identical); `.agents/skills/sdd-done/SKILL.md`
(the codex twin has no §9.1); `docs/sdd/WORKFLOW.md`; the parent spec `sdd-work-ledger.spec.md`;
any Python.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-done.md` | MODIFY | add reconciliation paragraph after §9.1 intro |
| `.agent/workflows/sdd-done.md` | MODIFY | same paragraph, same position |
| `docs/wiki/cheatsheet.md` | MODIFY | mention `--no-reconcile` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# none — documentation-only task
```

### Existing Signatures to Use
```text
# .claude/commands/sdd-done.md:412-417  (twin: .agent/workflows/sdd-done.md:306-311 — same text)
### 9.1. Snapshot Ledger Issues (FEAT-566)

For feature flows (not hotfixes), regenerate `sdd/ledger/issues.jsonl` from a
throwaway worktree at `origin/<BASE_BRANCH>` and commit/push it directly to
`base_branch` when it changed — never from an active worktree, never on the
feature branch. Bounded retry on a rejected push; never fails `/sdd-done`.

# docs/wiki/cheatsheet.md:253
wikitoolkit ledger audit · wikitoolkit ledger export --dest <dir> · wikitoolkit ledger compact
```
`EXPORT_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger export 2>&1)` at
`.claude/commands/sdd-done.md:440` is the script line the prose describes — it is NOT modified.

### Does NOT Exist
- ~~`.claude/skills/sdd-done/SKILL.md`~~ — no such file; the twins are exactly the two listed.
- ~~a `--reconcile` positive flag~~ — only `--no-reconcile` exists (TASK-4296).
- ~~`wikitoolkit ledger merge`~~ — no such subcommand; do not document one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".claude/commands/sdd-done.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-done.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/wiki/cheatsheet.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- The inserted paragraph must be byte-identical in both twins (AC-2 diff check).
- Do not touch the fenced bash block of §9.1, nor any other section.
- Keep the twins' existing line-wrap width (≈ 78 columns) for the new paragraph.

### References in Codebase
- `.claude/commands/sdd-done.md:412-464` — the whole §9.1 block for context.
- `sdd/specs/sdd-work-ledger.spec.md:659-665` — the original FEAT-566 wording of the snapshot step.

---

## Implementation Blueprint

### Steps (in order)
1. In `.claude/commands/sdd-done.md`, insert the paragraph block below after the §9.1 intro
   paragraph — *why*: the invariant belongs next to the step that relies on it.
2. Repeat verbatim in `.agent/workflows/sdd-done.md` — *why*: the twins must not drift.
3. Edit the cheatsheet line — *why*: it is the one-line reference operators grep.
4. Run the AC-2 diff command; it must print nothing.

### `.claude/commands/sdd-done.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c 'feature branch. Bounded retry on a rejected push; never fails `/sdd-done`.' .claude/commands/sdd-done.md) -->
<!-- AFTER — insert below `feature branch. Bounded retry on a rejected push; never fails `/sdd-done`.` (verified: .claude/commands/sdd-done.md:417), keeping one blank line before and after -->

The export **reconciles** against the committed snapshot (FEAT-671): rows for
issues this checkout's ledger has never seen are carried forward unchanged and
local state wins for issues it knows, so a run from a machine whose event log
is behind never drops other people's issues. `wikitoolkit ledger export
--no-reconcile` is the explicit, destructive opt-out — `/sdd-done` never uses it.
```
**Why**: this is the exact wording spec §3 M3 requires (carry-forward, local wins, never drops,
opt-out never used by `/sdd-done`). Insert the five lines plus the blank line; nothing else.

### `.agent/workflows/sdd-done.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c 'feature branch. Bounded retry on a rejected push; never fails `/sdd-done`.' .agent/workflows/sdd-done.md) -->
<!-- AFTER — insert below the same anchor (verified: .agent/workflows/sdd-done.md:311) -->
<!-- identical five-line paragraph as in .claude/commands/sdd-done.md above -->
```
**Why**: the twins must stay in lock-step — copy the paragraph, do not retype it.

### `docs/wiki/cheatsheet.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c 'wikitoolkit ledger audit · wikitoolkit ledger export --dest <dir> · wikitoolkit ledger compact' docs/wiki/cheatsheet.md) -->
<!-- REPLACE the anchor line (verified: docs/wiki/cheatsheet.md:253) with: -->
wikitoolkit ledger audit · wikitoolkit ledger export --dest <dir> [--no-reconcile] · wikitoolkit ledger compact
```
**Why**: documents the opt-out next to the command it belongs to.

### FILL IN checklist
- [ ] none — every block is final text; the only judgement is preserving surrounding blank lines.

---

## Acceptance Criteria

- [ ] AC-1 Both twins contain the new paragraph immediately after the §9.1 intro paragraph.
- [ ] AC-2 `diff <(sed -n '/^### 9.1/,/^```bash/p' .claude/commands/sdd-done.md) <(sed -n '/^### 9.1/,/^```bash/p' .agent/workflows/sdd-done.md)` prints nothing.
- [ ] AC-3 `git diff --stat` shows only the three listed files; the §9.1 bash block is unchanged (`git diff -U0 .claude/commands/sdd-done.md` touches no line inside the fence).
- [ ] AC-4 `docs/wiki/cheatsheet.md` line mentions `[--no-reconcile]`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_from_dir.py -q`

---

## Test Specification

Documentation-only task: no new tests. The pytest above is a smoke run proving the environment is
intact; the real checks are the AC-2/AC-3 shell commands.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug commands-sdd-done-fixes --feature-id FEAT-671`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — re-run the three `grep -c` anchor checks; each must print `1`
5. **Update status** in `sdd/tasks/index/commands-sdd-done-fixes.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — apply the three blocks exactly
7. **Verify** AC-1..AC-4 and run the Validation Command
8. **Commit the code** — stage only the three files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4297 commands-sdd-done-fixes verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
