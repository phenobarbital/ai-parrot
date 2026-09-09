# TASK-3037: Catalog-backed ContractCard datasource

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3029, TASK-3035, TASK-3036
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M5 in spec §3 and the corresponding normative §2 behavior. Covers AC5, AC6; full feature acceptance remains governed by spec §§4–5.

## Scope

- Implement ExtractDataSource subclass registered as contractcard, injecting tenant-bound catalog via source configuration.
- Route overlapping requested field sets in order obligation_id, person_id, party_id, contract_id; reject unknown/ambiguous requests.
- Export ISO dates, plain version dictionaries, denormalized counterparty names and catalog-wide Party aliases; return eight static standard seeds.
- Support standalone filters, while exposing a complete prevalidated domain snapshot for graph refresh.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/contracts/datasource.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot/tests/knowledge/contracts/test_datasource.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.ontology.refresh import OntologyRefreshPipeline, RefreshReport  # packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py:41
from parrot_loaders.extractors.base import ExtractDataSource, ExtractedRecord, ExtractionResult  # packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py:19
from parrot_loaders.extractors.factory import DataSourceFactory  # packages/ai-parrot-loaders/src/parrot_loaders/extractors/factory.py:13
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| ExtractDataSource.extract | async (self, fields: list[str] or None = None, filters: dict[str, Any] or None = None) -> ExtractionResult; list_fields() is async | packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py:70 |
| DataSourceFactory | register_api_source(cls, name: str, source_cls: type[ExtractDataSource]) -> None; get(self, source_name, source_config=None) instantiates name/config | packages/ai-parrot-loaders/src/parrot_loaders/extractors/factory.py:35 |
| OntologyRefreshPipeline.run | async (self, tenant_id: str, domain: str or None = None) -> RefreshReport; extract(fields=property_names), no filters | packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py:94 |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.
- OntologyRefreshPipeline.run has no filters argument and no atomic multi-collection publish; create_edges does not update existing edge properties.
- PropertyDef has no datetime/nested-model type; RelationDef has no symmetric flag.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3029`: Catalog aliases, audit, sources and publication state; inspect its completed artifact and committed interface before use.
- `TASK-3035`: Verification and refresh preserve human decisions; inspect its completed artifact and committed interface before use.
- `TASK-3036`: Contracts ontology vocabulary and allowlisted patterns; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Overlapping Person/Party/Obligation/Contract projections resolve correctly and malformed field requests fail.
- [ ] Merged aliases include all cards; versions serialize as lists and seeds are deterministic.
- [ ] Extraction errors cannot be returned as successful empty snapshots.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Overlapping Person/Party/Obligation/Contract projections resolve correctly and malformed field requests fail.
2. Merged aliases include all cards; versions serialize as lists and seeds are deterministic.
3. Extraction errors cannot be returned as successful empty snapshots.

Validation: `uv run pytest packages/ai-parrot/tests/knowledge/contracts/test_datasource.py -q`

Store execution logs in `artifacts/logs/task-3037.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3037-contracts-card-datasource.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Completed 2026-09-09 by sdd-worker (Claude Opus 5).

**Implementation**: created `parrot/knowledge/contracts/datasource.py`.
`ContractCardDataSource` subclasses `ExtractDataSource` (lazy import of the
ai-parrot-loaders satellite with an actionable error) and self-registers with
`DataSourceFactory.register_api_source('contractcard', ...)`; the tenant-bound
catalog is injected through the source config and validated at construction.
`infer_entity` tests key markers in the documented order — obligation_id,
person_id, party_id, contract_id, standard_id — because the requested field sets
overlap, then rejects any request that is not a subset of the matched entity
(`UnknownFieldRequest`). Projections emit ISO dates everywhere, plain version dicts
without card snapshots, denormalized `counterparty_names`, `card_revision` and
`active` for the graph's staleness/guard checks, catalog-wide unioned Party aliases,
signatory Person rows, obligation rows carrying their contract's active flag, and the
eight static ComplianceStandard seeds (independent of any card, so `requires` edges
can be discovered after seeding). `snapshot()` returns all five prevalidated entity
sets for the graph loader's preflight; standalone filters (contract_id/status/
verification/party_id) are supported and unknown filters rejected.

**Validation**: `pytest .../test_datasource.py -q` -> 22 passed (whole contracts
suite 405 passed, `artifacts/logs/task-3037.log`); ruff clean. Tests cover
registration through the real factory, every entity's own field set routing to
itself, the three documented overlaps, ambiguous/unknown requests, ISO dates and
plain versions, alias union across cards, static seeds, retracted-card exclusion,
field narrowing, filters, the full snapshot, and — critically — that a catalog
failure propagates instead of being returned as a successful empty snapshot (which
the generic diff would read as "delete everything").

**Deviations**: none.
