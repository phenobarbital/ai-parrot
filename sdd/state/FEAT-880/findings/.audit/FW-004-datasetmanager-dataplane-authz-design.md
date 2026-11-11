---
id: FW-004
query_id: Q008
type: wiki_query
intent: "Find DatasetManager data-plane authorization (FEAT-228) design: AuthorizingDataSource, RLS."
executed_at: 2026-11-11T22:20:00Z
duration_ms: 0
parent_id: null
depth: 1
---

# FW-004 — DatasetManager already has its own PBAC + RLS layer: every registered source is wrapped in `AuthorizingDataSource`, which fails OPEN without a guard or PermissionContext

## Summary

FEAT-228 (`dataplane-authz` spec) chose "Option D": an `AuthorizingDataSource(inner, guard, pctx_provider)`
decorator whose `fetch()` runs driver:connect → table:read/source:read → RLS predicate injection →
`inner.fetch()`. A central `_make_source()` factory wraps every source when a `DataPlanePolicyGuard` is
configured, so a new semantic source would be wrapped automatically. RLS templates live in an
`RlsRegistry` keyed by `(driver, table)` — the same registry type the semantic toolkit syncs its policy
`rls:` rules into. Two asymmetries versus the semantic pipeline: (1) the chain is fail-open when there
is no guard or no `PermissionContext` ("backwards compat") and fail-closed only on the sensitive path;
(2) this side has no column masking, member grants, row limits or signed audit ledger. FEAT-738 later
made RLS injection request-scoped (`request_scoped_copy`) and states the semantic layer is unaffected.

## Citations

- wiki: `file:sdd/specs/dataplane-authz.spec.md` (Q008 score=0.13), `sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py#AuthorizingDataSource` (score=0.26), `file:sdd/tasks/completed/TASK-1496-authorizing-data-source.md` (score=0.65), `file:sdd/specs/handlers-datasets-fixes.spec.md` (score=0.06), `sym:packages/ai-parrot/src/parrot/auth/dataplane_guard.py#DataPlanePolicyGuard` (score=0.00)
- path: `sdd/specs/dataplane-authz.spec.md`
  lines: 56-58
  symbol: `Goals`
  excerpt: |
    - Ensure fail-open backward compatibility when no guard is configured (matching
    - Enforce fail-closed on the sensitive path (SQL parse failure, missing session,
- path: `sdd/specs/dataplane-authz.spec.md`
  lines: 80-89
  symbol: `Overview`
  excerpt: |
    **Chosen approach: Option D — `AuthorizingDataSource` decorator + central factory.**
    A central `_make_source()` factory in `DatasetManager.fetch_dataset` (and in
- path: `sdd/specs/dataplane-authz.spec.md`
  lines: 117
  symbol: `Enforcement Chain`
  excerpt: |
    1. ctx = _pctx_var.get()                # None → fail-open (backwards compat)
- path: `sdd/specs/dataplane-authz.spec.md`
  lines: 205
  symbol: `RlsRule`
  excerpt: |
    Registry entry: template predicate keyed by (driver, table).
- path: `sdd/specs/dataplane-authz.spec.md`
  lines: 247
  symbol: `AuthorizingDataSource`
  excerpt: |
    class AuthorizingDataSource(DataSource):
- path: `sdd/specs/dataplane-authz.spec.md`
  lines: 261
  symbol: `RlsRegistry`
  excerpt: |
    (driver, table) → predicate template with subject-attribute placeholders.
- path: `sdd/specs/dataplane-authz.spec.md`
  lines: 306
  symbol: `Module 5: RLS Predicate Injection`
  excerpt: |
    ### Module 5: RLS Predicate Injection
- path: `sdd/specs/handlers-datasets-fixes.spec.md`
  lines: 10-13
  symbol: `FEAT-738`
  excerpt: |
    **Feature ID**: FEAT-738
    **Status**: approved
- path: `sdd/specs/handlers-datasets-fixes.spec.md`
  lines: 56-62
  symbol: `Goals`
  excerpt: |
    The semantic layer (FEAT-704) is unaffected — it clones the AST per request and hands off
    - G1. RLS injection is **request-scoped**: a `fetch()` call never mutates `self._inner`.
- path: `sdd/specs/handlers-datasets-fixes.spec.md`
  lines: 112
  symbol: `request_scoped_copy`
  excerpt: |
    - Public `request_scoped_copy(source: DataSource) -> DataSource`: returns `copy.copy(source)`

## Notes

- Governance implication for FEAT-880: running semantic-compiled SQL through a plain SQL source gets
  DatasetManager's PBAC + RLS only when a guard *and* a pctx are present, and never the semantic
  policy's member grants, masks, limits or audit. If the semantic `GovernancePipeline` also runs, RLS
  could be injected twice from the same `(driver, table)` registry.
- The spec text quoted here is the *design*; whether `_make_source()` exists under that name today was
  not checked in this lane.
- [cross-lane: type=read, intent=check sources/authorizing.py for how a compiled-SQL source is classified (general vs opaque driver mode), whether RLS would be re-injected on already-governed SQL, and the real name of the wrapping factory in tool.py]
