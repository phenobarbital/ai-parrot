# TASK-3035: Verification and refresh preserve human decisions

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3034
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M4 in spec §3 and the corresponding normative §2 behavior. Covers AC4, AC11; full feature acceptance remains governed by spec §§4–5.

## Scope

- Implement verify_card(contract_id, fields, *, user, expected_revision) and refresh_card(contract_id, *, source=None). fields=None verifies the whole card; mappings target only explicit paths.
- Stamp actor/time; manual origin only for corrected values. Resolve required evidence gaps, low-confidence unresolved fields and stale_fields before marking whole card verified.
- Refresh compares hashes of nonempty exact quotes; preserve verified values, rebind unchanged evidence, and retain prior values plus separate stale candidates for changed/missing evidence.
- Maintain original/resulting snapshots, verified amendment effective history, unresolved dates and administrative recorded revisions; preserve manual owner overrides and retirement mappings with optimistic writes.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/contracts/library.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot/tests/knowledge/contracts/test_verification.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.pageindex.content_store import NodeContentStore  # packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:197
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| loader_for | (self, tree_name: str) -> Callable[[str], Optional[str]]; synchronous body reader | packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:197 |

### New design interfaces (not existing imports)

Implement only this task’s scoped portion; sibling methods belong to their designated dependencies or follow-up tasks.

| Interface | Normative contract from spec §2 |
|---|---|
| ContractLibrary | async add_contract(source, *, source_uri, force=False), add_folder(folder, *, recursive=False, force=False), verify_card(contract_id, fields, *, user, expected_revision), refresh_card(contract_id, *, source=None), relate_contracts(contract_ids=None, *, force=False); ingest returns card-or-null + added/updated/skipped and an explicit reason in the report |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3034`: Staged library ingestion and canonical source identity; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Partial/all verification, unchanged/moved/empty/changed quotes and changed values exercise precise provenance transitions.
- [ ] Concurrent verification/refresh rejects stale revision and retains previous verified values.
- [ ] Late-effective amendment, missing effective date and owner correction preserve proper version intervals and historical citations.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Partial/all verification, unchanged/moved/empty/changed quotes and changed values exercise precise provenance transitions.
2. Concurrent verification/refresh rejects stale revision and retains previous verified values.
3. Late-effective amendment, missing effective date and owner correction preserve proper version intervals and historical citations.

Validation: `uv run pytest packages/ai-parrot/tests/knowledge/contracts/test_verification.py -q`

Store execution logs in `artifacts/logs/task-3035.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3035-contracts-library-verification.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Completed 2026-09-09 by sdd-worker (Claude Opus 5).

**Implementation**: extended `contracts/library.py`. `verify_card(contract_id,
fields, *, user, expected_revision)`: a mapping confirms (origin untouched) or
corrects (origin -> `manual`, confidence 1.0) only the named paths, always stamping
`verified_by`/`verified_at`; `fields=None` verifies every non-rule field and marks
the whole card verified **only** when `_verification_blockers` is empty (missing
evidence, unresolved low confidence, remaining unverified fields, stale fields).
Corrections recompute the derived notice/renewal dates and the status. Writes go
through the catalog with optimistic revisions. `merge_verified_fields` (hooked into
every update, i.e. every refresh) compares each previously verified field's stored
quote against the refreshed bodies: a nonempty verbatim match preserves the verified
value and rebinds the evidence to its new node; changed/missing evidence — and an
empty quote, which never proves anything — keeps the prior value, stores the incoming
one as `candidate` and marks the field stale. `refresh_card` re-cards from
`source`/`source_path`/`source_uri` under the existing canonical URI.
`apply_amendment_history` appends a contractual interval to the base contract only
when the amendment has a resolved parent and a *verified* effective date; it is
idempotent and never invents a date. `get_card_field`/`set_card_field` address
top-level, `term.*`, `parties.<id>.*` and `obligations.<id>.*` paths and raise on
unknown ones.

**Validation**: `pytest .../test_verification.py -q` -> 25 passed; whole contracts
suite **353 passed** (`artifacts/logs/task-3035.log`); ruff clean. Tests exercise
confirm vs correct provenance transitions, partial vs whole-card verification,
blocker reporting, rule fields never being human-verified, derived recomputation,
manual termination, a stale `expected_revision` being rejected while the first
writer's value survives, all four refresh evidence cases (unchanged / moved node /
changed / empty quote), a changed value with unchanged evidence keeping the human
decision, an end-to-end refresh that preserves a correction while the v1 citation
still resolves, and amendment history for verified / unverified / undated /
parentless cases.

**Deviations**: none.
