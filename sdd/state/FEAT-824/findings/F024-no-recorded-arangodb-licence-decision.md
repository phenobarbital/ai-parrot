---
id: F024
query_id: Q204
type: wiki_query
intent: "Recorded decisions / ADRs about ArangoDB, licensing or graph backends"
executed_at: 2026-11-06T13:29:04Z
duration_ms: 4000
parent_id: null
depth: 0
merged_from: [FW-004]
---

# F024 — The wiki holds no decision, ADR or lesson about the ArangoDB licence or about removing ArangoDB; the only Arango-related memories are two driver lessons and one test-gate lesson

## Summary

Four category-scoped queries on the local namespace (`decision`, `adr`, `lesson`, `gotcha`) plus an unscoped query for "ArangoDB license BUSL removal" returned **no** page recording the licence problem, a removal decision, or a chosen successor engine. The single `adr` hit is unrelated (memory-less clients). The decision-category hits are about LanceDB (FEAT-542) and unrelated features. Three `lesson` memories mention ArangoDB, all operational: the asyncdb driver's missing `execute_query`, AQL `UPSERT` ERR 1501, and a backend-parity test that fails (not skips) without `ARANGODB_HOST`. So the "ArangoDB must be removed" premise lives only in the source draft; every approved spec in the repo (FEAT-540, FEAT-670 — see F030, F031) still treats ArangoDB as a supported peer backend.

## Citations

- path: `mem-587973959640` (wiki memory, category lesson)
  symbol: `asyncdb ArangoDB driver: execute_query adapter and create_graph key spelling`
  wiki_page_id: mem-587973959640
  score: 0.67
  excerpt: |
    The asyncdb 'arangodb' driver exposes query(aql, bind_vars) -> (rows, error) and no execute_query();
    OntologyGraphStore needs execute_query, so callers wrap the connection (ArangoQueryAdapter in
    agents/contracts_agent.py, ArangoAdapter in the contracts integration tests). Its create_graph documents
    python-arango style edge definitions but the vendored arangoasync wants collection/from/to keys (ERR 1941);
    OntologyGraphStore.initialize_tenant now retries with the other spelling.

- path: `packages/ai-parrot/tests/knowledge/wiki/decisions/test_backend_parity.py`
  symbol: `FEAT-578 backend-parity test`
  wiki_page_id: mem-6bce6fa75b05
  score: 1.00
  excerpt: |
    FEAT-578's backend-parity test is an AC8 honesty guard, not a normal test: it FAILS — it does not skip —
    whenever a live backend is unreachable, unless ADR_PARITY_A… [truncated in the stub]

- path: `mem-d52f56cf3a46` (wiki memory, category lesson)
  symbol: `ERR 1501: UPSERT example attribute names must be literal`
  wiki_page_id: mem-d52f56cf3a46
  score: 0.30
  excerpt: |
    ArangoDB rejects both a bind parameter and a computed name as the attribute name of an UPSERT example object (ERR 1501).

## Notes

- Absence is the finding: no `adr:` page, no `decision` memory and no `gotcha` covers ArangoDB licensing, BUSL, or SurrealDB. Queries run: `"decision ArangoDB graph backend"`, `"ArangoDB license BUSL removal"`, `"lesson arangodb backend gotcha"`, and `"arangodb graph backend postgres"` with `--ns local --category {decision,adr,lesson,gotcha}`.
- The FEAT-578 parity test implies the ADR decision plane has an Arango parity requirement: removing the Arango wiki backend also changes that test's contract (it names `ARANGODB_HOST`).
- The spec should record the licence decision as an ADR (the repo has a decision plane, FEAT-578) so that FEAT-670's "ArangoDB is not retired" non-goal is explicitly superseded.
- [cross-lane: type=git_log, intent=search commit messages for BUSL / licence / remove arango to confirm no prior removal decision exists in history]
- [cross-lane: type=read, intent=read tests/knowledge/wiki/decisions/test_backend_parity.py to see which backends the AC8 parity guard requires]
