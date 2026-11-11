# TASK-5522: Documentation — wiki/tools/semantic-layer.md: Semantic datasets in DatasetManager (M6)

**Feature**: FEAT-880 — DatasetManager semantic source — add_semantic()
**Spec**: `sdd/specs/datasetmanager-semantic-source.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5517, TASK-5518, TASK-5519, TASK-5520, TASK-5521
**Assigned-to**: unassigned

---

## Context

Spec §10: docs policy required; one section in an existing page.

---

## Scope

Add a section 'Semantic datasets in DatasetManager' covering: registration (both forms), the `conditions` query shape, identity resolution (bound, bridged, fail-closed), per-subject frames, session isolation, row cap and the `semantic` / `inline_complete` / `complete` response fields, what is never cached, when to re-fetch, and when to prefer `sl_query_metrics`.

**NOT in scope**: code changes.

---

## Files to Create / Modify

| File | Action | Purpose |
|---|---|---|
| `wiki/tools/semantic-layer.md` | MODIFY | new section |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `254caceeb8` on `dev`. Re-verify before writing code.

### Verified Imports
```python
# none
```

### Existing Signatures to Use
```python
# Read the merged code of TASK-5517..5521 for exact names before writing.
```

### Does NOT Exist
- ~~a DuckDB-backed dataset store~~ — out of scope (FEAT-713 revision); do not document it as available.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/tools/semantic-layer.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Follow `sdd/templates/techwiki-page.md` conventions; describe only shipped behavior.

### References in Codebase
- `wiki/tools/semantic-layer.md` — existing 'Guarded dataset hand-off' section (the push direction).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Read the merged implementation.
2. Append the section after the hand-off section.
3. Run the techwiki check.

### `wiki/tools/semantic-layer.md` (MODIFY)
```markdown
## Semantic datasets in DatasetManager

<!-- FILL IN: sections listed in Scope — bounded by shipped behavior only. -->
```

### FILL IN checklist
- [ ] every Scope bullet covered.

---

## Acceptance Criteria

- [ ] Section present and accurate
- [ ] `parrot sdd techwiki check` passes for the spec

---

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_e2e_dataset_source.py -q`

Also run (acceptance, not a registered test runner):
`parrot sdd techwiki check --spec sdd/specs/datasetmanager-semantic-source.spec.md --root .`

---

## Test Specification

n/a (documentation).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug datasetmanager-semantic-source --feature-id FEAT-880`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/datasetmanager-semantic-source.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/datasetmanager-semantic-source.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands with
   `PYTHONPATH` set to the absolute `src` dirs of every changed package (worktree rule)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5522 datasetmanager-semantic-source verified`
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
