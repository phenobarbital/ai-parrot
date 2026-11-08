# TASK-5251: Licence ADR + FEAT-670 supersession

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 2. The decision to retire ArangoDB and adopt PostgreSQL + SurrealDB reverses
positions recorded by FEAT-540 and FEAT-670 (both say ArangoDB stays), and SurrealDB is the
research note's *third* choice. The repository records such decisions as ADRs under
`docs/decisions/`; this task writes one and marks FEAT-670 (HelixDB provider) superseded.

**Precondition (spec §8 open question, owner Jesus Lara):** the research note
`sdd/proposals/Grafos open source para ai-parrot.md` must be tracked in git before this task
lands — the ADR cites it by path. Check with `git ls-files "sdd/proposals/Grafos open source para ai-parrot.md"`;
if it prints nothing, stop and report the blocker instead of committing.

---

## Scope

- Create `docs/decisions/graph-backends-postgres-surrealdb.md` in the repository ADR format:
  frontmatter `id`, `title`, `status: accepted`; sections `## Context`, `## Decision`,
  `## Consequences`, `## Decision Metadata` (YAML block).
- Context cites the research note and the four selection criteria (open-source non-enterprise;
  no paid SaaS; deployable on the AWS services in use; simpler platform) and states the licence
  problem: ArangoDB binaries/Docker images ship under a Community License without commercial-use
  rights and with a 100 GiB cap.
- Decision states: PostgreSQL (vocabulary, GraphIndex, vectors) + SurrealDB 3.3.x server mode
  (instance graph, wiki knowledge store), subject to the G1 verdict; why PostgreSQL + AGE (not
  installable on Amazon RDS) and FalkorDB (SSPL, per-graph write serialisation, no BM25) — ranked
  first and second by the note — were passed over; why BSL 1.1 is acceptable for SurrealDB (its
  binaries carry no commercial-use restriction; ai-parrot does not redistribute them); that the
  FEAT-540 and FEAT-670 positions that ArangoDB stays are reversed; HelixDB rejected (single writer
  process, GPL-3.0 Python client).
- Consequences: removal is the last phase (D-P7); the research note's advice to keep ArangoDB as
  an optional adapter is not followed, and why.
- Decision Metadata mirrors the spec's `## Decisions` entries (spec lines 1456–1514), with
  `document_id: seed-graph-backends-postgres-surrealdb`.
- In `sdd/specs/helixdb-provider.spec.md`, change `**Status**: approved` to
  `**Status**: superseded by FEAT-824 (sdd/specs/ontology-backend.spec.md)`.

**NOT in scope**: changing FEAT-670's 26 pending tasks in `sdd/tasks/index/helixdb-provider.json`
(spec §8 open question — how they leave `/sdd-next` is the owner's call); editing FEAT-540 files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/decisions/graph-backends-postgres-surrealdb.md` | CREATE | the ADR |
| `sdd/specs/helixdb-provider.spec.md` | MODIFY | status line only |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# none — documentation only
```

### Existing Signatures to Use
```text
docs/decisions/history-single-writer.md         # format reference: frontmatter id/title/status,
                                                # ## Context, ## Decision, ## Consequences, ## Decision Metadata
packages/ai-parrot/tests/knowledge/wiki/decisions/test_seed_rules.py:37   # parametrises EVERY docs/decisions/*.md:
    # frontmatter parses with no diagnostics; status == "accepted";
    # parse_spec_decisions(heading=SEED_HEADING) → no diagnostics, no waivers;
    # block.document_id == f"seed-{path.stem}";
    # every entry.about ⊂ sdd/taxonomy/subsystems.yaml ids; every target prefix in {sym,file,dir}
    # and the target path exists.
sdd/specs/helixdb-provider.spec.md:14           # "**Status**: approved"  (occurrences: 1)
```

### Does NOT Exist
- ~~a `knowledge-ontology` subsystem~~ — use only `knowledge-graphindex` / `knowledge-wiki` in `about`.
- ~~`docs/decisions/graph-backends-postgres-surrealdb.md`~~ — created here.
- ~~`packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/`~~ as an ADR target — it does not
  exist yet at this point in the graph; target only existing files.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/decisions/graph-backends-postgres-surrealdb.md", "action": "CREATE"},
    {"path": "sdd/specs/helixdb-provider.spec.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `test_seed_rules.py::test_all_nine_seeds_present` uses `>=` on the expected set, so a tenth ADR
  is allowed; `test_seed_parses_and_resolves` will parametrise the new file — it must pass.
- Copy the spec's six Decisions entries; keep `contradicts`/`supersedes` lists empty (the reversed
  FEAT-540/670 positions predate the decision records and are named in prose).

---

## Implementation Blueprint

### Steps (in order)
1. Verify the research note is tracked (Context precondition) — *why*: the ADR cites it.
2. Write the ADR from the block below — *why*: the format is enforced by `test_seed_rules.py`.
3. Edit the FEAT-670 status line — *why*: spec AC Phase 1 #4.
4. Run the validation command.

### `docs/decisions/graph-backends-postgres-surrealdb.md` (CREATE)
````markdown
---
id: ADR-0010
title: Graph backends — retire ArangoDB for PostgreSQL + SurrealDB
status: accepted
---

## Context

Source: `sdd/proposals/Grafos open source para ai-parrot.md`; `sdd/specs/ontology-backend.spec.md` (FEAT-824).

<!-- FILL IN: licence problem, four selection criteria, engines compared — bounded by Scope bullets 2 -->

## Decision

<!-- FILL IN: engines per plane, G1 gate, AGE/FalkorDB/HelixDB/JanusGraph rejections, BSL 1.1
     acceptance, FEAT-540 and FEAT-670 positions reversed — bounded by Scope bullet 3 -->

## Consequences

<!-- FILL IN: removal last (D-P7), optional-adapter advice not followed, FEAT-670 superseded -->

## Decision Metadata

```yaml
schema_version: 1
document_id: seed-graph-backends-postgres-surrealdb
entries:
  # FILL IN: the six entries of sdd/specs/ontology-backend.spec.md ## Decisions (lines 1460-1513),
  #          verbatim ids/statements/relations/about/targets/rationale/rejected_alternatives.
```
````
**Why this shape**: identical section set and metadata contract to the nine seed ADRs; the
`id` value is free text (check the highest `ADR-` id among existing files and use the next one).

### `sdd/specs/helixdb-provider.spec.md` (MODIFY)
```text
# occurrences: 1 (verified: grep -c '**Status**: approved' sdd/specs/helixdb-provider.spec.md)
# REPLACE line 14 `**Status**: approved` with:
**Status**: superseded by FEAT-824 (sdd/specs/ontology-backend.spec.md)
```

### FILL IN checklist
- [ ] Context, Decision, Consequences prose — bounded by Scope.
- [ ] Six Decision Metadata entries copied from the spec.
- [ ] ADR `id` value.

---

## Acceptance Criteria

- [ ] The ADR exists in the repository format, cites the research note and the four criteria, and
      names FEAT-540 and FEAT-670 as the positions it reverses.
- [ ] `sdd/specs/helixdb-provider.spec.md` carries `**Status**: superseded by FEAT-824 (…)`.
- [ ] `test_seed_rules.py` passes with the new ADR parametrised.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_seed_rules.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug ontology-backend --feature-id FEAT-824`).
2. Check the research-note precondition first.
3. Mark `in-progress`, implement, run the Validation Commands, commit only the files listed above.
4. Close with `parrot sdd task close TASK-5251 ontology-backend verified`; fill in the Completion Note.

---

## Completion Note

Seat: qwen3-coder-480b · Backend: nova · Attempts: 1 · Duration: 285s. Merge-tier validation green.

**Completed by**: sdd-worker (coder: qwen3-coder-480b)
**Date**: 2026-11-07
**Notes**:

**Deviations from spec**: none
