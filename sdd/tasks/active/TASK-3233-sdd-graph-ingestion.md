# TASK-3233: SDD specification and task graph ingestion

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3226, TASK-3227, TASK-3230, TASK-3231
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. Specs and per-spec indexes become queryable `spec:` and `task:` nodes, with dependency and declared code-scope edges.

## Scope

- Implement `SDDGraphIngest.ingest_all()` over the shared root's SDD specs and per-spec indexes.
- Parse feature metadata, task status/dependencies, and scoped file references into `implements`, `blocks`, and `touches` edges.
- Make repeated ingestion idempotent through LedgerStore connection-scoped writers.
- Test legacy/missing fields, dependencies, and explicit file scope.

**NOT in scope**: changing SDD artifact formats, rendering CLI output, or scanning undeclared source.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py` | CREATE | SDD parser/projector. |
| `tests/knowledge/wiki/test_ledger_sdd_ingest.py` | CREATE | Idempotent graph-ingest coverage. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
`scripts.sdd.sdd_meta.parse` accepts a `Path` and returns `FlowMeta`. `LedgerStore` is created by TASK-3230; `WikiPageRecord` exists in `store.py:362`.

### Existing Signatures to Use
`parse(doc_path: Path) -> FlowMeta` is the metadata parser. Per-spec task indexes live at `sdd/tasks/index/*.json`.

### Does NOT Exist
- ~~a monolithic `sdd/tasks/.index.json` contract~~ — use `sdd/tasks/index/*.json` only.
- ~~automatic ingestion on every file save~~ — explicit ingest only.

## Acceptance Criteria

- [ ] Specs/tasks have stable `spec:`/`task:` IDs.
- [ ] Dependency/file-scope edges are queryable and repeated ingest is idempotent.
- [ ] Linked worktrees read only shared-checkout artifacts.
- [ ] `pytest tests/knowledge/wiki/test_ledger_sdd_ingest.py -q` passes.

## Test Specification

Use small temporary SDD fixtures and assert exact pages and edges.
