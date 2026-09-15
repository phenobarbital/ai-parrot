---
id: F006
query_id: Q005
type: read
intent: Existing tests pin dispatch and cover adapter behavior
executed_at: 2026-09-09T23:24:11.921Z
parent_id: null
depth: 1
---

# F006 — Existing tests pin dispatch and cover adapter behavior

## Summary

The satellite tests assert the complete dispatch mapping, so adding a key requires updating their expectations. Adapter tests cover FTS detection, normalized native ranks and propagated errors. Toolkit tests cover grouped/merged output, timeout/error isolation and skipped FTS origins. FAISSStore offers an existing local vector-only pattern with optional import checks and save/load persistence.

## Citations

- path: `packages/ai-parrot-embeddings/tests/test_store_backends_present.py`
  lines: 7-37,49-55
  symbol: `test_supported_stores_unchanged`
  excerpt: |
    assert supported_stores == {

- path: `packages/ai-parrot-embeddings/tests/test_namespace_imports.py`
  lines: 126-139
  symbol: `test_supported_stores_unchanged`
  excerpt: |
    assert supported_stores == {

- path: `packages/ai-parrot-tools/tests/multistoresearch/test_vector_origin.py`
  lines: 1-68
  symbol: `test_fts_capability_detection`
  excerpt: |
    assert VectorStoreOrigin(store=FakeArango(), name="arango").supports_fts is True

- path: `packages/ai-parrot-tools/tests/multistoresearch/test_toolkit.py`
  lines: 60-145
  symbol: `test_timeout_isolated / test_error_isolated / test_fts_skips_non_capable`
  excerpt: |
    assert by["slow"].status == "timeout"

- path: `packages/ai-parrot-embeddings/src/parrot/stores/faiss_store.py`
  lines: 21-47,89-92
  symbol: `FAISSStore`
  excerpt: |
    class FAISSStore(AbstractStore):

## Notes

Tests were inspected, not run; no implementation exists in this proposal. Proposed acceptance tests must exercise a real temporary LanceDB directory with deterministic embeddings, not only fake adapters.
