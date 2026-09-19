# TASK-3466: `/sdd-status` and `/sdd-next` — `--project` / `--tag` filters

**Feature**: FEAT-576 — SDD Document Taxonomy (`projects` and `tags` frontmatter)
**Spec**: `sdd/specs/sdd-spec-changes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3461
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 5** (G6, AC8). The per-spec index header is deliberately NOT
extended (spec Non-Goals), so both commands resolve the taxonomy from the spec through the
`doc_taxonomy` CLI (TASK-3461) and intersect with each index header's `spec` field.

---

## Scope

For `sdd-status` and `sdd-next`, in all three copies:
- Document `--project <p>` / `--tag <t>` (repeatable) in Usage.
- When either is given, run
  `python -m scripts.sdd.doc_taxonomy --kind spec --paths-only [--project P]... [--tag T]...`
  and keep only indexes whose header `spec` is in that output. `_orphans.json` is always
  excluded under a taxonomy filter (it has no spec).
- `/sdd-status` prints `Projects: … · Tags: …` under each feature panel's `Spec:` line
  (resolve with `doc_taxonomy --json --kind spec`).

**NOT in scope**: changing index JSON; editing `doc_taxonomy.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-status.md` | MODIFY | usage, filter step, panel line |
| `.agent/workflows/sdd-status.md` | MODIFY | identical edit (twin) |
| `.agents/skills/sdd-status/SKILL.md` | MODIFY | workflow step 1 filter |
| `.claude/commands/sdd-next.md` | MODIFY | usage + filter in step 1 |
| `.agent/workflows/sdd-next.md` | MODIFY | identical edit (twin) |
| `.agents/skills/sdd-next/SKILL.md` | MODIFY | workflow step 1 filter |

---

## Codebase Contract (Anti-Hallucination)

### Existing anchors (verified 2026-09-19)
```text
.claude/commands/sdd-status.md
  :10-14  ## Usage block: "/sdd-status" and "/sdd-status <feature-name>" inside a ``` fence
  :26-35  step 1: header fields list, `ALL=$(jq -s '.' sdd/tasks/index/*.json)`,
          "If a `<feature-name>` filter is provided, show only the index whose ..."   (:34)
  :57-58  panel lines "Feature: <feature>" / "Spec: sdd/specs/<feature>.spec.md"
.claude/commands/sdd-next.md   (NO ## Usage section today — add one after the title paragraph, before "## Guardrails" at :11)
  :19-26  step 1 with `TASKS=$(jq -s '[.[] | select(.feature != "_orphans") | .tasks[]]' sdd/tasks/index/*.json)`
.agents/skills/sdd-status/SKILL.md:10 "Invocation: `sdd-status [<feature-name>]`." ; workflow step 1 at :22-24
.agents/skills/sdd-next/SKILL.md  workflow step 1 "Aggregate tasks:" (~:24-25)
```
- Twin diffs today: `sdd-status` differs only in frontmatter line 2 (`model:` vs `description:`); `sdd-next` differs only at the "Worktree policy" line (:116). Keep it that way.

### CLI contract (from TASK-3461 — do not change)
`python -m scripts.sdd.doc_taxonomy --kind spec --paths-only --project P --tag T` → repo-relative
spec paths, one per line, exit 0 even when empty. `--json` → list of
`{"path","kind","projects","tags"}`. Filter values are alias-normalized (`formdesigner` works).

### Does NOT Exist
- ~~`tags`/`projects` in `sdd/tasks/index/*.json` headers~~ — do NOT read them from the index
- ~~`jq` support for YAML~~ — the taxonomy comes only from the CLI

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/commands/sdd-status.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-status.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-status/SKILL.md", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-next.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-next.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-next/SKILL.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add usage lines, then the filter paragraph + bash snippet in step 1 of each command — *why*: AC8.
2. Mirror to `.agent/workflows` twins byte-identically; add the one-line rule to `.agents/skills`.

### `.claude/commands/sdd-status.md` + twin (MODIFY — Usage)
```markdown
# occurrences: 1 (verified: grep -c '^/sdd-status <feature-name>$' .claude/commands/sdd-status.md)
# AFTER — insert below `/sdd-status <feature-name>`:
/sdd-status --project <project> [--project …] [--tag <tag> …]
```

### `.claude/commands/sdd-status.md` + twin (MODIFY — step 1)
````markdown
# occurrences: 1 (verified: grep -c 'If a `<feature-name>` filter is provided' .claude/commands/sdd-status.md)
# AFTER the "If a `<feature-name>` filter …" paragraph (:34-35), insert:
If `--project` / `--tag` is given (FEAT-576), resolve the matching specs from
their frontmatter — the index header does not carry taxonomy — and keep only
indexes whose `spec` is in the list (AND across flags, OR within a repeated
flag; `_orphans.json` is excluded because it has no spec):

```bash
SPECS=$(python -m scripts.sdd.doc_taxonomy --kind spec --paths-only --project <p> --tag <t>)
ALL=$(jq -s --arg specs "$SPECS" '[.[] | select(.spec as $s | ($specs | split("\n")) | index($s))]' sdd/tasks/index/*.json)
```

Under each panel's `Spec:` line print `Projects: <a, b> · Tags: <x, y>` from
`python -m scripts.sdd.doc_taxonomy --kind spec --json` (omit the line when both are empty).
````
# FILL IN: add the `Projects:` line to the sample panel after `Spec: sdd/specs/<feature>.spec.md` (:58) — bounded by one line

### `.claude/commands/sdd-next.md` + twin (MODIFY)
````markdown
# Usage — BEFORE `## Guardrails` (verified: :11), insert:
## Usage
```
/sdd-next
/sdd-next --project <project> [--tag <tag>]     # FEAT-576 taxonomy filter
```

# Step 1 — AFTER the `TASKS=$(jq ...)` fence (:24-26), insert the same SPECS resolution and:
```bash
TASKS=$(jq -s --arg specs "$SPECS" '[.[] | select(.feature != "_orphans") | select(.spec as $s | ($specs | split("\n")) | index($s)) | .tasks[]]' sdd/tasks/index/*.json)
```
(only when a taxonomy flag was given).
````

### `.agents/skills/sdd-{status,next}/SKILL.md` (MODIFY)
```markdown
- Optional `--project` / `--tag` (FEAT-576): get matching spec paths from
  `python -m scripts.sdd.doc_taxonomy --kind spec --paths-only ...` and keep only indexes whose `spec` is listed.
```
(add to workflow step 1; for sdd-status also extend the Invocation line.)

### FILL IN checklist
- [ ] sample panel `Projects:` line in sdd-status (identical in twin)
- [ ] verify the `jq` expression on a real index before committing: run it with `SPECS=sdd/specs/sdd-spec-changes.spec.md`

---

## Acceptance Criteria

- [ ] Both commands document `--project`/`--tag` and use `doc_taxonomy --paths-only` (AC8)
- [ ] No task-index schema change (AC8)
- [ ] Twin diffs unchanged from today (sdd-status: frontmatter line only; sdd-next: Worktree-policy line only)
- [ ] The jq filter, run against the real repo with `SPECS=sdd/specs/sdd-spec-changes.spec.md`, returns exactly the `sdd-spec-changes` index

---

## Validation Commands
- `pytest tests/sdd_scripts/test_command_contracts.py -q`
- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`

---

## Test Specification

No new test file (prompt documents). The jq-expression check in the Acceptance Criteria is
the functional verification — record its output in the Completion Note.

---

## Agent Instructions

1. Read spec §3 Module 5. Confirm TASK-3461 is done (the CLI must exist to test the jq filter).
2. Apply edits, run the jq check + Validation Commands, fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-coder (native, haiku), via sdd-worker orchestration (FEAT-549)
**Date**: 2026-09-19
**Notes**: Added `--project`/`--tag` documentation to `/sdd-status` and `/sdd-next`
(all 3 mirrors each): usage lines, a filter paragraph resolving matching specs via
`doc_taxonomy --kind spec --paths-only` and keeping only indexes whose `spec` is in
that list (AND across flags, OR within a repeated flag; `_orphans.json` excluded),
and a "Projects: ... · Tags: ..." line on the status panel. No task-index schema
change (AC8).

Verification: jq filter tested against the real repo with
`SPECS=sdd/specs/sdd-spec-changes.spec.md`, correctly isolated to FEAT-576's index.
`pytest tests/sdd_scripts/test_command_contracts.py tests/sdd_scripts/
test_command_twin_parity.py -q` → 14 passed.

Review: no defects found (`coder-review:5345ed1ad9c565a71eb9948e`), fix_commits=[].

Seat: haiku (native) · Backend: native · Model: haiku · Attempts: 1 · Duration: n/a · Tokens: n/a

**Deviations from spec**: none
