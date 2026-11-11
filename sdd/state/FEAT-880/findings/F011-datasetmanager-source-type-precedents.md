---
id: F011
query_id: Q036
type: git_log
intent: "History of DatasetManager sources (who adds source types, how)."
executed_at: 2026-11-11T22:05:20Z
duration_ms: 0
parent_id: null
depth: 0
lane_id: FG-004
---

# F011 — No new source type in 120 days; precedents are one-file-per-source tasks (FEAT-060 Iceberg/Mongo/Delta, FEAT-062 Composite) and a 6-file authz layer (dataplane-authz)

## Summary

In the last 120 days `sources/` only received fixes (4 commits: QuerySlugSource tenant/principal work in FEAT a2ui-linked-surfaces, fail-closed slug authz, request-scoped RLS). The file-creation history (`--diff-filter=A`) gives the sizing precedent: each data source kind was added as **one new file under `sources/`** — three kinds in a single commit for `datasetmanager-sources` (TASK-420/421/422), `CompositeDataSource` in one task (TASK-431). The data-plane authorization layer (`dataplane-authz`, 2026-06-08) then added five cross-cutting files that every source now passes through: `dialects.py`, `resolver.py`, `opaque.py`, `rls.py`, `authorizing.py`.

## Citations

- sha: `bc0e0499e3`  date: 2026-03-24
  message: "feat(datasetmanager-sources): TASK-420/421/422 — IcebergSource, MongoSource, DeltaTableSource"
  files added: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/deltatable.py`, `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/iceberg.py`, `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/mongo.py`
- sha: `1952913136`  date: 2026-03-25
  message: "feat(composite-datasets): TASK-431 — CompositeDataSource with JoinSpec, filter propagation, chained JOINs"
  files added: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/composite.py`
- sha: `24007c1666`  date: 2026-03-23
  message: "migrated from pipelines to parrot-pipelines"
  files added (repo-layout move, original sources): `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py`, `sql.py`, `table.py`, `query_slug.py`, `memory.py`, `airtable.py`, `smartsheet.py`, `__init__.py`, `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
- sha: `108c229d7e`  date: 2026-06-08  message: "feat(dataplane-authz): TASK-1490 — Driver–Dialect Map"  files added: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/dialects.py`
- sha: `bdea78fd1a`  date: 2026-06-08  message: "feat(dataplane-authz): TASK-1491 — Physical-Resource Resolver"  files added: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py`
- sha: `1a9493782b`  date: 2026-06-08  message: "feat(dataplane-authz): TASK-1492 — Opaque-Source Resolvers"  files added: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/opaque.py`
- sha: `ba096265fa`  date: 2026-06-08  message: "feat(dataplane-authz): TASK-1494 — RLS Predicate Injection"  files added: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/rls.py`
- sha: `103f9188b6`  date: 2026-06-08  message: "feat(dataplane-authz): TASK-1496 — AuthorizingDataSource Decorator"  files added: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py`
- sha: `55619c5ceb`  date: 2026-10-24  message: "fix(dataset-manager): TASK-4678 — request-scoped RLS injection"  files added: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/scoped_copy.py`
- sha: `81b207e9be`  date: 2026-09-26  message: "feat(a2ui-linked-surfaces): TASK-3779 — QuerySlugSource tenant/principal/MultiQS/close + to_qs_principal"  files: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py`
- sha: `a44cf79608`  date: 2026-10-14  message: "feat(fixgroup-04e6aabc0d26): TASK-4288 — fail-closed slug authorization on the QuerySlugSource fetch path"  files: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py`

## Notes

- Sizing read: a `SemanticSource` is plausibly "one new source file + one `add_semantic` method on `tool.py` + a resolver entry + tests" — the same shape as TASK-431. But unlike 2026-03, a new source must now also declare itself to the physical-resource resolver (`resolver.py` / `opaque.py`), the driver–dialect map and RLS injection, or it will be either rejected fail-closed or (worse) unrecognised by the authz wrapper.
- DatasetManager therefore has **its own** PBAC + RLS layer (`AuthorizingDataSource`, `rls.py`) independent of the semantic layer's `GovernancePipeline` — two governance stacks would apply to one semantic-sourced dataset; the synthesis must decide which is authoritative.
- [cross-lane: type=read, intent=read packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py and opaque.py to see how a source kind maps to physical resources and what an unregistered kind does (fail-closed?)]
- [cross-lane: type=wiki_query, intent=find the dataplane-authz spec (FEAT-228) to compare its RLS/PBAC model with the semantic GovernancePipeline]
