# TASK-3036: Contracts ontology vocabulary and allowlisted patterns

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3025
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. May run alongside ready tasks with disjoint owned files after all dependencies complete. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M5 in spec §3 and the corresponding normative §2 behavior. Covers AC5; full feature acceptance remains governed by spec §§4–5.

## Scope

- Install and correct proposal contracts YAML: five domain entities, original eleven relations plus conflicts_with/references_obligation, ten patterns and English search view; base merge must be 8/16/13.
- Use versions as list and existing vocabulary; judged edges have origin=llm with no automatic discovery. Add active endpoint guards, precise bind sets, search contract mapping and identity-based family deduplication.
- Use default-deny reader OR owner policy plus authenticated my_contracts restriction. Test same_department with a Contract fixture, conventional tenant database and ANY-target semantics; keep v1 YAML role-based as specified.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/contracts.ontology.yaml` | CREATE | Task-owned deliverable |
| `packages/ai-parrot/tests/knowledge/contracts/test_ontology_domain.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.ontology.parser import OntologyParser  # packages/ai-parrot/src/parrot/knowledge/ontology/parser.py:19
from parrot.knowledge.ontology.merger import OntologyMerger  # packages/ai-parrot/src/parrot/knowledge/ontology/merger.py:54
from parrot.knowledge.ontology.authorization import AuthorizationChecker  # packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py:43
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| OntologyParser.load / OntologyMerger.merge | load(path: Path) -> OntologyDefinition; merge(self, yaml_paths: list[Path]) -> MergedOntology | packages/ai-parrot/src/parrot/knowledge/ontology/parser.py:29; packages/ai-parrot/src/parrot/knowledge/ontology/merger.py:54 |
| AuthorizationChecker.check | async (self, spec: AuthorizationSpec, user_context: dict[str, Any], resolved_entities: dict[str, str], tenant_id: str) -> tuple[bool, str or None]; OR rules | packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py:62 |
| _check_same_department | DOCUMENT(@target_id).department; matches any target, constructs tenant_id + "_ontology" database | packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py:293 |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.
- OntologyRefreshPipeline.run has no filters argument and no atomic multi-collection publish; create_edges does not update existing edge properties.
- PropertyDef has no datetime/nested-model type; RelationDef has no symmetric flag.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3025`: Typed contract models and standard aliases; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Parser/merger validate expected entity/relation/pattern counts and all eight standards referenced by domain.
- [ ] Every one of ten pattern bind declarations matches its AQL use, including nullable kind and Employee _id.
- [ ] same_department spike records verified behavior without enabling a broader policy; real AQL execution is required again by integration gate.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Parser/merger validate expected entity/relation/pattern counts and all eight standards referenced by domain.
2. Every one of ten pattern bind declarations matches its AQL use, including nullable kind and Employee _id.
3. same_department spike records verified behavior without enabling a broader policy; real AQL execution is required again by integration gate.

Validation: `uv run pytest packages/ai-parrot/tests/knowledge/contracts/test_ontology_domain.py -q`

Store execution logs in `artifacts/logs/task-3036.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3036-contracts-ontology-domain.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Completed 2026-09-09 by sdd-worker (Claude Opus 5).

**Implementation**: installed the proposal YAML at
`ontology/defaults/domains/contracts.ontology.yaml` (v1.0) with the spec §2
corrections: added the two LLM-judged relations `conflicts_with` (Contract-Contract,
canonicalised pair traversed with ANY) and `references_obligation`
(Obligation-Obligation, cross-contract), both carrying `origin` (llm|manual, default
llm), confidence, rationale, judged_at and both endpoint source hashes, and both with
**no discovery rules** so the generic field-match pass can never write them; added
`active` to Contract and Obligation plus `card_revision` to Contract; added
`active != false` guards to all ten patterns (including obligation endpoints);
rewrote `contract_family` to de-duplicate by contract `_key` instead of by the whole
{contract, rel, depth} object; documented the exact bind set of every pattern in its
description (nullable `@kind` always bound, `@user_id` a full `employees/<id>`
graph _id from the trusted context); documented the search-hit -> contract mapping;
and replaced `hybrid_concept_match`/`fuzzy_name_match` with `exact_id_match` because
the contracts adapter resolves ids against the authorized catalog itself.

**Validation**: `pytest .../test_ontology_domain.py -q` -> 28 passed; the real
`OntologyParser`/`OntologyMerger` merge base+contracts into exactly **8 entities,
16 relations, 13 patterns**. Whole contracts suite 381 passed
(`artifacts/logs/task-3036.log`); the existing ontology suite still passes
(206 passed); ruff clean.

**same_department spike (spec §8 open question)**: RESOLVED by test against a
Contract fixture — `AuthorizationChecker._check_same_department` executes
`RETURN DOCUMENT(@target_id).department` (a generic field read, so a Contract
supplies `department` exactly like an Employee), constructs the conventional
`<tenant>_ontology` database, and matches ANY resolved entity (it stops at the first
match). The rule is therefore usable but is deliberately **not** enabled: v1 YAML
stays role-based (contract_reader OR contract_owner, default deny) plus the
authenticated `my_contracts` restriction, and a test asserts no pattern declares
`same_department`.

**Deviations**: none. Real AQL execution against ArangoDB with live bind values
remains an integration gate (TASK-3054) — parsing is explicitly not evidence that the
queries run.
