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

**Completed by**: sdd-worker orchestrator (attempt 3, self-implemented per FEAT-549 protocol)
**Date**: 2026-09-19
**Notes**: Added the "Document Taxonomy (FEAT-576)" section to `sdd/WORKFLOW.md`
immediately before `## Release Cut`: the `projects`/`tags` key shapes and
normalization rules, a "Querying" subsection (`doc_taxonomy` flags), "Where they
are used" (`/sdd-status`, `/sdd-next`, `/sdd-tojira`, wiki summary), and
"Backfill" (`backfill_taxonomy`, dry-run default, `--apply`, never commits).

Verified every CLI flag against the landed code (not copied from the spec
blindly), per AC12:

```
$ python -m scripts.sdd.doc_taxonomy --help
usage: python -m scripts.sdd.doc_taxonomy [-h] [--root ROOT]
                                          [--kind {spec,brainstorm,proposal,all}]
                                          [--project PROJECT] [--tag TAG]
                                          [--paths-only | --json | --summary]
options: -h/--help, --root ROOT, --kind {...}, --project PROJECT, --tag TAG,
--paths-only, --json, --summary

$ python -m scripts.sdd.backfill_taxonomy --help
usage: python -m scripts.sdd.backfill_taxonomy [-h] [--root ROOT]
                                               [--kind {spec,brainstorm,proposal,all}]
                                               [--limit LIMIT] [--apply]
options: -h/--help, --root ROOT, --kind {...}, --limit LIMIT (stop after N
proposed edits, 0 = no limit), --apply (write the edits, default: dry run)
```

Verification: `pytest tests/sdd_scripts/test_command_contracts.py -q` → 12
passed. `git status --porcelain` before commit showed exactly the 1 task-listed
file.

**Attempt history / engine limitation found**: attempt 1 (qwen) timed out
(`APITimeoutError`, infra failure). Attempt 2 (mistral) produced CORRECT content
— byte-for-byte the section this Completion Note documents, verified by reading
the sub-worktree's commit directly — but was rejected by the merge fidelity gate
as `fidelity_violation` / `unexpected_files: ["sdd/WORKFLOW.md"]`. This is a
genuine engine-policy conflict, not a coder defect: `sdd/WORKFLOW.md` is this
task's own explicit, correctly-declared MODIFY target (spec §3 Module 9, AC12),
yet the fidelity gate appears to blanket-reject ANY path under `sdd/` regardless
of the task's own Complexity Contract declaring it. Filed in the final feature
ledger for follow-up (the gate needs an exception for a task whose *own*
declared target legitimately lives under `sdd/`, as opposed to a coder
gratuitously touching `sdd/tasks/`/`sdd/tasks/index/` state it was never asked
to touch). No model feedback filed — mistral's delivery was correct.

**Deviations from spec**: none
