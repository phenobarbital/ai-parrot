---
id: F020
query_id: Q040
type: read
intent: "Read one per-spec index header to confirm the real header fields."
executed_at: 2026-11-07T01:25:27Z
duration_ms: 500
parent_id: null
depth: 0
merged_from: [FC-020]
---

# F020 — Per-spec index header has 10 top-level keys incl. completed_at, parallel_semantics, validation_contract, test_contract (schema 2)

## Summary

`sdd/tasks/index/pageindex-generation-publication.json` (FEAT-831, just merged) confirms the header: `feature`, `feature_id`, `spec`, `type`, `base_branch`, `created_at`, `completed_at` (set `2026-11-07T00:52:52+00:00` by close_task/sdd-done), `parallel_semantics` ("exclusive"), `validation_contract` ("required"), `test_contract` ({schema: 2, runners: [{kind: "pytest", targets: [...]}]}) then `tasks[]`. The brainstorm's assumed field list (`feature, feature_id, spec, type, base_branch, created_at, completed_at, tasks[]`) is correct but incomplete — three contract-style blocks were added since (FEAT-699/709), which is a precedent for adding an `escrow` block to the header as another contract-style key.

## Citations

- path: `sdd/tasks/index/pageindex-generation-publication.json`
  lines: 1-12
  symbol: null
  excerpt: |
    {
      "feature": "pageindex-generation-publication",
      "feature_id": "FEAT-831",
      "spec": "sdd/specs/pageindex-generation-publication.spec.md",
      "type": "feature",
      "base_branch": "dev",
      "created_at": "2026-11-06T23:27:45Z",
      "completed_at": "2026-11-07T00:52:52+00:00",
      "parallel_semantics": "exclusive",
      "validation_contract": "required",
      "test_contract": {

## Notes

- `completed_at` here is the "worker/sdd-done graded itself" timestamp (FC-005).
