# TASK-2770: OQ3 spike — KNN under graph filter, CTE order, ANN index choice

**Feature**: FEAT-520 — GraphIndex Postgres Backend
**Spec**: `sdd/specs/graphindex-postgres-backend.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2767, TASK-2769
**Assigned-to**: unassigned

---

## Context

Spec §8 open question OQ3 and the declared FIRST task of Module 7: filtering
pgvector KNN by a graph-expansion subset can defeat the ANN index. Before
TASK-2771 freezes the `hybrid_retrieve` CTE order, this spike measures both
directions and picks the ANN index default (TASK-2769 left `hnsw` as
provisional). **Deliverable is a report + two recorded decisions, not
production code.**

---

## Scope

- Build a benchmark script (`scripts/` or `packages/ai-parrot/scripts/` —
  match repo precedent: `packages/ai-parrot/scripts/benchmark_reranker.py`
  exists) that:
  1. Seeds a synthetic-but-realistic corpus into a throwaway schema
     (~10k–50k node_versions, embeddings at the configured dim, a scale-free
     edge set, 2–3 temporal generations of versions).
  2. Measures, at hood sizes ~10 / ~100 / ~1000 (graph expansion depth 1–3):
     - **graph→semantic**: recursive CTE first, KNN restricted to the hood
       (exact scan) vs ANN with iterative index scan (pgvector ≥ 0.8).
     - **semantic→graph**: KNN top-N first, graph expansion from survivors.
  3. Compares HNSW vs IVFFlat build/query on the corpus.
  4. Captures `EXPLAIN (ANALYZE, BUFFERS)` for each variant.
- Write findings to `artifacts/logs/feat-520-oq3-spike.md`: numbers table +
  two decisions: (a) default CTE strategy (possibly cardinality-dependent
  with the threshold), (b) ANN index default for `ensure_ann_index`.
- Update `pg_schema.py`'s ANN default + config docstring if the spike
  contradicts the provisional `hnsw` choice (one-line change, allowed).
- Flip spec §8 OQ3 checkbox to resolved with a one-line answer + pointer to
  the artifact (commit alongside).

**NOT in scope**: implementing `hybrid_retrieve` (TASK-2771 consumes the
decisions), BOE ingestion (synthetic corpus suffices for the mechanics;
note in the report that a real-corpus re-run belongs to legal-wiki work).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/scripts/benchmark_graph_knn.py` | CREATE | spike harness (reproducible, seeded RNG) |
| `artifacts/logs/feat-520-oq3-spike.md` | CREATE | findings + decisions |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py` | MODIFY (maybe) | ANN default if contradicted |
| `sdd/specs/graphindex-postgres-backend.spec.md` | MODIFY | flip OQ3 to `[x]` with answer |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex.pg_schema import create_pg_pool, ensure_schema, ensure_ann_index  # TASK-2764/2769
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence   # TASK-2765
```

### Existing Signatures to Use
```python
# packages/ai-parrot/scripts/benchmark_reranker.py — the repo's benchmark-harness
# precedent (structure, argparse, reproducibility) — follow its shape.
# pgvector ≥ 0.8 iterative scan knobs (verify against installed server version):
#   SET hnsw.iterative_scan = 'relaxed_order';  -- and ivfflat.iterative_scan
```

### Does NOT Exist
- ~~a BOE corpus fixture in the repo~~ — generate synthetic data; do not
  invent a loader.
- ~~`hybrid_retrieve`~~ — not implemented yet (TASK-2771); the spike queries
  are hand-written SQL prototypes of its CTEs.

---

## Implementation Notes

### Key Constraints
- Run with `ENV=prod`? NO — this spike runs against the local Postgres
  (resolved `GRAPHINDEX_PG_DSN`, defaulting to `parrot.conf.default_dsn`),
  never a shared/production database; the throwaway schema is created and
  dropped by the script.
- Seeded RNG; print the seed into the report for reproducibility.
- Time with `\timing`-equivalent (Python monotonic around fetch), median of
  ≥5 runs per cell.

### References in Codebase
- Spec §7 Known Risks (OQ3 mitigations list) — the hypotheses to test.

---

## Acceptance Criteria

- [ ] Report exists with the numbers table, EXPLAIN excerpts, seed, and the
      TWO decisions stated explicitly.
- [ ] Spec OQ3 flipped to `[x]` with the answer + artifact pointer.
- [ ] `ensure_ann_index` default consistent with the decision.
- [ ] Script is re-runnable (`python benchmark_graph_knn.py --dsn ...`).

---

## Test Specification

No pytest suite — the deliverable is the benchmark artifact. The script must
exit non-zero on any failed run so CI/humans notice a broken harness.

---

## Agent Instructions

1. Read spec §3 Module 7 + §7 risks; TASK-2769's ANN provisional choice.
2. Keep the spike honest: report what loses, not only what wins.
3. Update index status; move to completed + note when done.

---

## Completion Note

*(Agent fills this in when done)*
