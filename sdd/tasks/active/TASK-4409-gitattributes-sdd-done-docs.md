# TASK-4409: `.gitattributes`, `/sdd-done` §9.1 (three twins), docs, integration tests

**Feature**: FEAT-694 — Shared Ledger Event Log (cross-machine sync via git hooks)
**Spec**: `sdd/specs/ledger-shared-event-log.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4407, TASK-4408
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 + the M5 `/sdd-done` wiring. Makes git merge the shared log by union, makes
`/sdd-done` 9.1 the single writer that exports, rotates and commits the shared log alongside
`issues.jsonl`, documents the model, and adds the end-to-end integration tests.

---

## Scope

- Create `.gitattributes` exactly as spec §3 M4.
- `/sdd-done` §9.1 in **all three twins**: `.claude/commands/sdd-done.md`,
  `.agent/workflows/sdd-done.md`, `.agents/skills/sdd-done/SKILL.md` (the spec names only the
  first; the other two carry the same step — keep them in sync, see Notes).
- `docs/wiki/cheatsheet.md` §5 and `docs/sdd/WORKFLOW.md`: shared log, four hooks, the commands,
  "re-run `parrot claude install` once".
- `tests/knowledge/wiki/test_ledger_shared_log_integration.py` (four spec §4 integration tests).

**NOT in scope**: committing `sdd/ledger/events.jsonl` (TASK-4410); editing the FEAT-671 spec.

---

## Attempt-2 status (orchestrator note)

Attempt 1 already delivered: `.gitattributes` (exists — verify only), `.claude/commands/sdd-done.md` and
`.agent/workflows/sdd-done.md` §9.1. It OMITTED and attempt 2 MUST deliver: `.agents/skills/sdd-done/SKILL.md`
(codex twin, prose form, same §9.1 change), `docs/wiki/cheatsheet.md`, `docs/sdd/WORKFLOW.md`, and
`tests/knowledge/wiki/test_ledger_shared_log_integration.py`. Do not redo the finished files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.gitattributes` | MODIFY | `merge=union` for the shared log + archives |
| `.claude/commands/sdd-done.md` | MODIFY | §9.1 export-log + rotate-log + stage/restore `sdd/ledger` |
| `.agent/workflows/sdd-done.md` | MODIFY | same §9.1 change (twin) |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | same §9.1 change (codex twin, prose form) |
| `docs/wiki/cheatsheet.md` | MODIFY | §5 ledger commands + shared log |
| `docs/sdd/WORKFLOW.md` | MODIFY | "Where things live" rows |
| `tests/knowledge/wiki/test_ledger_shared_log_integration.py` | CREATE | integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.service import LedgerService                 # verified: cli.py:127
from parrot.knowledge.wiki.ledger.sdd_ingest import SDDGraphIngest             # verified: cli.py:3644 (lazy import)
from parrot.knowledge.wiki.store import SQLitePragmaPolicy                     # verified: service.py:37
```

### Existing Signatures to Use
```text
.claude/commands/sdd-done.md:438 and :461  `git -C "$TEMP_WORKTREE" restore --staged --worktree -- sdd/ledger/issues.jsonl >/dev/null 2>&1`  (2 occurrences)
.claude/commands/sdd-done.md:446           `EXPORT_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger export 2>&1)`
.claude/commands/sdd-done.md:447           `if [[ "$EXPORT_OUTPUT" != *"(changed)"* ]]; then`
.claude/commands/sdd-done.md:452           `git -C "$TEMP_WORKTREE" add sdd/ledger/issues.jsonl`
.agent/workflows/sdd-done.md               same lines: add ×1, restore ×2, export ×1 (verified grep -c)
.agents/skills/sdd-done/SKILL.md:170       prose: "`git add sdd/ledger/issues.jsonl`, commit `sdd: ledger snapshot for <FEAT-ID>`," (no restore lines)
docs/wiki/cheatsheet.md:253                `wikitoolkit ledger audit · wikitoolkit ledger export --dest <dir> [--no-reconcile] · wikitoolkit ledger compact`
docs/sdd/WORKFLOW.md:27                    `| \`sdd/ledger/issues.jsonl\` | Committed snapshot of the work ledger (written by \`/sdd-done\`) |`
```
Commands available after TASK-4406/4408: `wikitoolkit ledger export-log`, `import-log`, `rotate-log`.

### Does NOT Exist
- ~~`.gitattributes`~~ at repo root — you create it.
- ~~`sdd/ledger/archive/`~~ — created lazily by rotation; no `.gitkeep`.
- ~~any hook running `rotate-log`~~ — forbidden (AC18).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".gitattributes", "action": "CREATE"},
    {"path": ".claude/commands/sdd-done.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-done.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-done/SKILL.md", "action": "MODIFY"},
    {"path": "docs/wiki/cheatsheet.md", "action": "MODIFY"},
    {"path": "docs/sdd/WORKFLOW.md", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_shared_log_integration.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService"
  ]
}
```

---

## Implementation Notes

- **Restore must also drop untracked archive files.** `git restore --staged --worktree -- sdd/ledger`
  does not delete a *new* untracked `sdd/ledger/archive/events-*.jsonl`; after a rejected push the
  retry would rotate again into a stale archive (duplicate lines), and `git worktree remove`
  (no `--force`) refuses a dirty tree. Pair each restore with
  `git -C "$TEMP_WORKTREE" clean -fdq -- sdd/ledger >/dev/null 2>&1`. This is a refinement of
  spec §3 M4 — record it under "Deviations" in the Completion Note.
- `.claude/` and `.agent/` files may be git-ignored-but-tracked; stage with `git add -f` if needed
  (memory: prompt twins need `git add -f`).
- Integration tests: `from_dir` services under `tmp_path`, a shared `repo` dir; for
  `test_git_union_merge_has_no_conflict` run real `git init` with the `.gitattributes` line and
  `git -c user.name=t -c user.email=t@t commit`. For `test_rebuild_not_triggered_by_import_e2e`
  ingest a minimal spec/task via `SDDGraphIngest` (check its constructor in `ledger/sdd_ingest.py`
  before use) or assert pages written directly through the store survive.

---

## Implementation Blueprint

### Steps (in order)
1. `.gitattributes` — *why*: AC6, union merge for append-only files.
2. `.claude/commands/sdd-done.md` §9.1, then mirror into the two twins — *why*: AC11/AC18; twins drift otherwise.
3. Docs — AC13.
4. Integration tests; Validation Commands.

### `.gitattributes` (CREATE)
```gitattributes
# FEAT-694: the shared ledger event log is append-only on every machine; take both sides.
sdd/ledger/events.jsonl merge=union
sdd/ledger/archive/*.jsonl merge=union
```

### `.claude/commands/sdd-done.md` (MODIFY)
```bash
# occurrences: 2 (verified: grep -cF 'restore --staged --worktree -- sdd/ledger/issues.jsonl' .claude/commands/sdd-done.md)
# disambiguated: (a) line 438 is the first line inside `cleanup_snapshot_worktree() {`;
#                (b) line 461 follows `# Rejected push: re-sync the throwaway worktree only, re-export, retry.`
# REPLACE each with:
        git -C "$TEMP_WORKTREE" restore --staged --worktree -- sdd/ledger >/dev/null 2>&1
        git -C "$TEMP_WORKTREE" clean -fdq -- sdd/ledger >/dev/null 2>&1

# occurrences: 1 — REPLACE lines 446-452 (from `EXPORT_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger export 2>&1)`
# through `git -C "$TEMP_WORKTREE" add sdd/ledger/issues.jsonl`) with:
        EXPORT_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger export 2>&1)
        LOG_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger export-log 2>&1)
        ROTATE_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger rotate-log --older-than-days 30 2>&1)
        if [[ "$EXPORT_OUTPUT" != *"(changed)"* && "$LOG_OUTPUT" != *"(+"* && "$ROTATE_OUTPUT" != *"Rotated"* ]]; then
            echo "📝 Ledger snapshot unchanged — nothing to commit."
            break
        fi

        git -C "$TEMP_WORKTREE" add sdd/ledger/issues.jsonl sdd/ledger/events.jsonl
        [ -d "$TEMP_WORKTREE/sdd/ledger/archive" ] && git -C "$TEMP_WORKTREE" add sdd/ledger/archive
# FILL IN: update the "No --force" comment above cleanup_snapshot_worktree (it says the checkout
# "only ever touches issues.jsonl") and the prose of §9.1 to mention events.jsonl + rotation.
```
**Why**: 9.1 is the single serialized base-branch writer, the only place rotation may run (spec §3 M4).

### `.agent/workflows/sdd-done.md` / `.agents/skills/sdd-done/SKILL.md` (MODIFY)
```text
# FILL IN: .agent twin — apply the identical edits (same anchors, verified counts add×1 restore×2 export×1).
# FILL IN: .agents SKILL.md:170 — rewrite the prose step to: run `wikitoolkit ledger export`,
# `export-log`, `rotate-log --older-than-days 30` in the throwaway worktree; `git add`
# issues.jsonl + events.jsonl (+ archive/ when present); restore+clean `sdd/ledger` on cleanup.
```

### Docs (MODIFY)
```markdown
<!-- docs/wiki/cheatsheet.md — AFTER line 253 (occurrences: 1) -->
<!-- FILL IN: a "Shared event log (FEAT-694)" paragraph: sdd/ledger/events.jsonl + archive/, the four
     parrot-ledger hooks, `ledger export-log|import-log|rotate-log`, re-run `parrot claude install` once. -->

<!-- docs/sdd/WORKFLOW.md — AFTER line 27 (occurrences: 1) -->
| `sdd/ledger/events.jsonl` / `sdd/ledger/archive/` | Shared ledger event log (FEAT-694) — synced by the `parrot-ledger` git hooks; rotated only by `/sdd-done` |
```

### `tests/knowledge/wiki/test_ledger_shared_log_integration.py` (CREATE)
```python
"""FEAT-694 — end-to-end shared ledger log across isolated machines."""
# FILL IN: test_two_machines_converge_via_shared_file, test_git_union_merge_has_no_conflict,
# test_rebuild_not_triggered_by_import_e2e, test_fresh_clone_after_rotation_sees_everything (spec §4)
```

### FILL IN checklist
- [ ] three sdd-done twins in sync; comment updated
- [ ] cheatsheet paragraph
- [ ] four integration tests

---

## Acceptance Criteria

- [ ] AC4 (test half), AC6, AC11, AC13, AC17 (fresh clone), AC18.
- [ ] Twins carry the same §9.1 behaviour.

## Validation Commands

- `pytest tests/knowledge/wiki/test_ledger_shared_log_integration.py -q`

---

## Test Specification

Spec §4 "Integration Tests".

---

## Agent Instructions

Standard SDD flow (`sdd/templates/task.md` § Agent Instructions); feature worktree
`feat-FEAT-694-ledger-shared-event-log`; `PYTHONPATH=packages/ai-parrot/src`; close with
`scripts/sdd/close_task.sh TASK-4409 ledger-shared-event-log verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: `clean -fdq -- sdd/ledger` paired with each restore (see Notes); twins edited.
