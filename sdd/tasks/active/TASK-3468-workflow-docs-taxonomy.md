# TASK-3468: Document the SDD taxonomy in `sdd/WORKFLOW.md`

**Feature**: FEAT-576 — SDD Document Taxonomy (`projects` and `tags` frontmatter)
**Spec**: `sdd/specs/sdd-spec-changes.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3459, TASK-3461, TASK-3463
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 9** (AC12). A single reference section for humans: what the
keys mean, the vocabulary and aliases, the warn-not-fail rule, how to filter, and how to
run the backfill.

---

## Scope

- Add `## Document Taxonomy (FEAT-576)` to `sdd/WORKFLOW.md` immediately before `## Release Cut`.
- Cite the real CLI flags from TASK-3461/TASK-3463 (read the landed code — do not copy from the spec blindly).

**NOT in scope**: `docs/sdd/WORKFLOW.md` (the older copy); CLAUDE.md.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/WORKFLOW.md` | MODIFY | new section before `## Release Cut` |

---

## Codebase Contract (Anti-Hallucination)

### Existing anchors (verified 2026-09-19)
```text
sdd/WORKFLOW.md
  :145  ## Flow Types (FEAT-145, refined by FEAT-187)
  :169  ---
  :171  ## Release Cut          (occurrences: 1)
```
Facts to document (from TASK-3459 / 3461 / 3463):
- `KNOWN_PROJECTS`, `PROJECT_ALIASES`, `parse_taxonomy` in `parrot.knowledge.wiki.ledger.sdd_meta` (re-exported by `scripts/sdd/sdd_meta.py`)
- `python -m scripts.sdd.doc_taxonomy [--kind …] [--project …] [--tag …] [--paths-only|--json|--summary]`
- `python -m scripts.sdd.backfill_taxonomy [--kind …] [--limit N] [--apply]` (dry-run default, never commits)
- `/sdd-status` / `/sdd-next` `--project` / `--tag`; `/sdd-tojira` labels; wiki spec-page summary

### Does NOT Exist
- ~~taxonomy in `sdd/tasks/index/*.json`~~ — state explicitly that the index does not carry it

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/WORKFLOW.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Read the landed `doc_taxonomy.py` / `backfill_taxonomy.py` `--help` output — *why*: document real flags.
2. Insert the section — *why*: AC12.

### `sdd/WORKFLOW.md` (MODIFY)
````markdown
# occurrences: 1 (verified: grep -c '^## Release Cut$' sdd/WORKFLOW.md)
# BEFORE — insert above `## Release Cut` (verified: :171)
## Document Taxonomy (FEAT-576)

Brainstorms, proposals and specs carry two organizational frontmatter keys:

```yaml
projects: [ai-parrot, ai-parrot-server]   # parts of the codebase the doc concerns
tags: [memory, compaction]                # free-form kebab-case keywords
```

- **projects** — `packages/*` distribution names plus the areas `sdd-tooling`,
  `dev-loop`, `admin-ui`, `docs`, `ci` (`KNOWN_PROJECTS`). Aliases normalize:
  `parrot-core` → `ai-parrot`, `formdesigner` → `parrot-formdesigner`, …
  Unknown values **warn but are kept**.
- **tags** — lowercased, spaces/underscores → `-`, deduplicated.
- Missing keys read as empty lists; the per-spec task index does not cache them.
- `/sdd-spec` copies both from the brainstorm/proposal.

# FILL IN: "Querying" subsection (doc_taxonomy examples incl. --summary), "Where they are used"
#   (/sdd-status, /sdd-next, /sdd-tojira labels, wiki summary), "Backfill" (dry-run then --apply,
#   review the diff, commit yourself) — bounded by the real CLI flags; ≤ 60 lines total

---

````

### FILL IN checklist
- [ ] Querying / Where used / Backfill subsections with real flags

---

## Acceptance Criteria

- [ ] `sdd/WORKFLOW.md` has the "Document Taxonomy (FEAT-576)" section before "Release Cut" (AC12)
- [ ] Every CLI flag mentioned exists in the landed scripts (verify with `python -m scripts.sdd.doc_taxonomy --help` and `python -m scripts.sdd.backfill_taxonomy --help`; paste both into the Completion Note)

---

## Validation Commands
- `pytest tests/sdd_scripts/test_command_contracts.py -q`

---

## Test Specification

Documentation only. The `--help` checks in the Acceptance Criteria confirm the documented flags exist.

---

## Agent Instructions

1. Confirm TASK-3459, 3461, 3463 are done; run both CLIs with `--help`.
2. Write the section, run Validation Commands, fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
