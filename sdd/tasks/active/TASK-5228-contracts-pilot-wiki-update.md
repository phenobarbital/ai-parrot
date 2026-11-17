# TASK-5228: Documentation — wiki/knowledge/contracts-pilot-acceptance.md (M7)

**Feature**: FEAT-815 — Contracts Pilot Signoff & End-to-End Validation
**Spec**: `sdd/specs/contracts-pilot-signoff-e2e.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5222, TASK-5223, TASK-5225, TASK-5226, TASK-5227
**Assigned-to**: unassigned

---

## Context

Spec §10 / docs.policy required; covers AC9. The page exists (moved by FEAT-801); update, do not recreate.

## Scope

- Replace the manual matrix procedure with the `parrot contracts pilot run-case|record|signoff` workflow and the YAML template path.
- Add an "E2E coverage" section listing the three scenarios and `parrot e2e run/verify --plan sdd/state/FEAT-815/e2e-plan.md`.
- Signoff section: state explicitly **pending** (Bob has not signed) — never claim acceptance.
- Retitle references from FEAT-539 AC15 to "FEAT-539 AC15, tracked by FEAT-815".

**NOT in scope**: Recording real pilot results (operational, needs Bob); code changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/contracts-pilot-acceptance.md` | MODIFY | CLI workflow, E2E coverage, pending signoff |

## Codebase Contract (Anti-Hallucination)

Re-verified on 2026-11-05 against `dev` (post `71ef3ad4c8`).

### Verified Imports

```python
# documentation only — no imports
```

### Existing Signatures to Use

| Anchor | Occurrences | Source |
|---|---|---|
| `# Contracts pilot acceptance — Bob's twelve cases (FEAT-539, AC15)` | 1 (verified grep -c) | `wiki/knowledge/contracts-pilot-acceptance.md:5` |
| `## How to run each case` | 1 | `:35` |
| `## Signoff` | 1 | `:140` |

### Does NOT Exist

- ~~`docs/knowledge/contracts-pilot-acceptance.md`~~ — moved to `wiki/` by FEAT-801.
- ~~A completed signoff~~ — none exists; do not write one.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/knowledge/contracts-pilot-acceptance.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

- Pydantic v2, strict type hints, Google docstrings, `logging.getLogger(__name__)` — never `print` (CLI output goes through `click.echo`).
- No real contract text anywhere in committed files (spec AC10): evidence is referenced only by `contract_id` / `node_id` / `version_n` / `answer_id`.
- Parallelism: documents CaseMatrix/PilotSignoff (TASK-5222), the `parrot contracts pilot` commands (TASK-5223) and the three E2E node IDs (TASK-5225 test_catalog_roundtrip.py, TASK-5226 test_graph_publication.py, TASK-5227 test_card_lookup.py).

## Implementation Blueprint

### Steps (in order)

1. Read the whole page first.
2. Apply the edits; keep frontmatter valid.
3. Run the techwiki check.

#### `wiki/knowledge/contracts-pilot-acceptance.md` (MODIFY)

```markdown
<!-- REPLACE the body of `## How to run each case` (verified :35, occurrences 1) -->
## How to run each case

1. Copy `sdd/state/FEAT-815/case_matrix_template.yaml`, fill in Bob's verbatim questions.
2. `parrot contracts pilot run-case --matrix <file> --case C1 --tenant <t> --dsn "$GRAPHINDEX_PG_DSN"`
3. `parrot contracts pilot record --case C1 --disposition pass|fail|skip|handoff --reviewer <name> --citation <contract_id>#<node_id>@v<n>`
4. `parrot contracts pilot signoff --reviewer <name> --matrix <file> [--sign]`
<!-- FILL IN: keep the existing pass criteria prose; adjust only what the CLI replaces -->

<!-- INSERT before `## Signoff` (verified :140, occurrences 1) -->
## E2E coverage
<!-- FILL IN: table of the 3 scenario ids + node ids from sdd/state/FEAT-815/e2e-plan.md, and the run/verify commands -->
```

**Why**: follow `sdd/templates/techwiki-page.md` frontmatter conventions already on the page; the signoff block must stay visibly pending so nobody reads the page as acceptance.


### FILL IN checklist

- [ ] CLI workflow text
- [ ] E2E coverage table
- [ ] Pending-signoff wording

## Acceptance Criteria

- [ ] Page documents the CLI, template path and E2E scenarios (AC9).
- [ ] Signoff shown as pending.
- [ ] `parrot sdd techwiki check` passes for the spec.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/contracts/test_pilot_matrix.py -q`  (docs task: real check is `parrot sdd techwiki check --spec sdd/specs/contracts-pilot-signoff-e2e.spec.md --root .` — see AC)

## Test Specification

Documentation task — validated by `parrot sdd techwiki check`.

## Agent Instructions

1. Read the spec and this task; confirm every `Depends-on` task is `done` in `sdd/tasks/index/contracts-pilot-signoff-e2e.json`.
2. Work in the feature worktree `feat-FEAT-815-contracts-pilot-signoff-e2e`; verify each Codebase Contract entry before writing code.
3. Implement only the files listed above; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Close with `parrot sdd task close TASK-5228 contracts-pilot-signoff-e2e verified` and fill in the Completion Note.

## Completion Note

*(Agent fills this in when done)*
