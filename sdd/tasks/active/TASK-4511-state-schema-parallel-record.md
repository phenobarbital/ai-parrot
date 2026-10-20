# TASK-4511: State schema — optional `research.parallel` record

**Feature**: FEAT-708 — sdd-proposal-parallel-research
**Spec**: `sdd/specs/sdd-proposal-parallel-research.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 4 (M4). The parallel dispatch layer (TASK-4513) checkpoints per-lane
status and a merge receipt into `state.json` under `phases.research.parallel`.
The schema must accept that object while staying valid for every existing
(sequential) `state.json` — the field is optional (AC: "`state.json` schema
validates with and without `research.parallel`").

## Scope

- Add an optional `parallel` property to the `research` phase record's second
  `allOf` branch in `sdd/templates/state.schema.json`.
- Add `$defs/lane_record`.

**NOT in scope**: the command text that writes the object (TASK-4513), tests
(TASK-4518), any other phase record.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/templates/state.schema.json` | MODIFY | add `parallel` to research properties + `$defs/lane_record` |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None — JSON Schema only.

### Existing Signatures to Use
```json
// sdd/templates/state.schema.json:103-121 (verified 2026-10-20)
"research": {
  "allOf": [
    {"$ref": "#/$defs/phase_record"},
    {
      "type": "object",
      "properties": {
        "queries_executed": ..., "queries_skipped": ..., "depth_reached": ...,
        "files_read": ..., "grep_calls": ..., "git_calls": ...,
        "truncated": {"type": "boolean"},
        "truncation_reason": {"type": ["string", "null"]}        // line 117 — last property
      }
    }
  ]
},
// :228  "$defs": { "phase_record": { ... } }   — phase_record is the ONLY def today
```

### Does NOT Exist
- ~~`research.parallel`~~ — added by this task
- ~~`$defs/lane_record`~~ — added by this task
- ~~`additionalProperties: false` on the research branch~~ — the branch is open; do not close it

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [{"path": "sdd/templates/state.schema.json", "action": "MODIFY"}],
  "contract_symbols": []
}
```

## Implementation Notes

### Key Constraints
- `parallel` itself uses `additionalProperties: false` (spec M4 skeleton); `lane_record` does not.
- Keep the file valid JSON (mind trailing commas) and keep 2-space indentation.
- Lane status enum is exactly `pending | running | completed | failed`.

## Implementation Blueprint

### Steps (in order)
1. Insert `parallel` after `truncation_reason` — because the research branch is the only place the dispatcher writes.
2. Add `lane_record` after `phase_record` in `$defs` — because `parallel.lanes.*` reference it.
3. `python -c "import json; json.load(open('sdd/templates/state.schema.json'))"` — catch comma errors.

### `sdd/templates/state.schema.json` (MODIFY) — research branch
```json
// occurrences: 1 (verified: grep -c '"truncation_reason": {"type": \["string", "null"\]}' sdd/templates/state.schema.json — re-check; if >1, anchor on the line inside "research")
// AFTER — replace `"truncation_reason": {"type": ["string", "null"]}` inside "research" (verified: state.schema.json:117) with:
                "truncation_reason": {"type": ["string", "null"]},
                "parallel": {
                  "type": "object",
                  "additionalProperties": false,
                  "properties": {
                    "enabled": {"type": "boolean"},
                    "fallback_reason": {"type": ["string", "null"]},
                    "lanes": {
                      "type": "object",
                      "properties": {
                        "codebase": {"$ref": "#/$defs/lane_record"},
                        "git": {"$ref": "#/$defs/lane_record"},
                        "wiki": {"$ref": "#/$defs/lane_record"}
                      }
                    },
                    "merge": {
                      "type": "object",
                      "properties": {
                        "started_at": {"type": "string", "format": "date-time"},
                        "completed_at": {"type": "string", "format": "date-time"},
                        "input_count": {"type": "integer", "minimum": 0},
                        "output_count": {"type": "integer", "minimum": 0},
                        "merged_count": {"type": "integer", "minimum": 0},
                        "audit_dir": {"type": "string"}
                      }
                    }
                  }
                }
```
**Why**: verbatim from spec M4; optional because nothing lists it in `required`.

### `sdd/templates/state.schema.json` (MODIFY) — `$defs`
```json
// AFTER — close of "phase_record" inside "$defs" (verified: state.schema.json:228-239), add sibling:
    "lane_record": {
      "type": "object",
      "properties": {
        "status": {"enum": ["pending", "running", "completed", "failed"]},
        "started_at": {"type": ["string", "null"], "format": "date-time"},
        "completed_at": {"type": ["string", "null"], "format": "date-time"},
        "duration_seconds": {"type": ["number", "null"], "minimum": 0},
        "findings_count": {"type": "integer", "minimum": 0},
        "queries_executed": {"type": "integer", "minimum": 0},
        "queries_skipped": {"type": "integer", "minimum": 0},
        "error": {"type": ["string", "null"]}
      }
    }
```

### FILL IN checklist
- [ ] Confirm the `truncation_reason` anchor you edit is the one inside `"research"` (synthesis may have a similar one)
- [ ] Comma after `phase_record`'s closing brace

## Acceptance Criteria

- [ ] Schema is valid JSON and a valid Draft 2020-12 schema
- [ ] An existing sequential `state.json` (no `parallel`) still validates
- [ ] A `state.json` with the spec §2 `parallel` example validates
- [ ] Unknown key inside `parallel` is rejected

## Validation Commands

- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-proposal-parallel-research --feature-id FEAT-708`)
2. **Read the spec** at `sdd/specs/sdd-proposal-parallel-research.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/sdd-proposal-parallel-research.json`
4. **Verify the Codebase Contract** — re-run every `grep -c` anchor check before editing;
   if an anchor moved, fix the blueprint first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `FILL IN`
7. **Verify** — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (`.claude/` paths need `git add -f`)
9. **Close** with `scripts/sdd/close_task.sh <TASK-ID> sdd-proposal-parallel-research verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
