# TASK-2771: `hybrid_retrieve` — one-pass SQL (graph + KNN + FTS + RRF) + re-ranking

**Feature**: FEAT-520 — GraphIndex Postgres Backend
**Spec**: `sdd/specs/graphindex-postgres-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-2767, TASK-2769, TASK-2770
**Assigned-to**: unassigned

---

## Context

Module 7 of FEAT-520 — the retrieval payoff (spec D6/G5). Three candidate
legs run as CTEs of ONE SQL statement against the same snapshot: temporal
graph expansion from router seeds, pgvector KNN, and tsvector FTS; RRF fusion
happens in SQL; cross-encoder re-ranking happens in Python through the
existing `parrot/rerankers` seam. The method is named **`hybrid_retrieve`** —
NOT `hybrid_search`, which already exists on `PgVectorStore` (spec C2).
TASK-2770's spike decisions govern CTE order.

---

## Scope

- Implement on `PostgresPersistence`:
  ```python
  async def hybrid_retrieve(self, ctx, *, query_embedding=None, fts_terms=None,
      seeds=None, as_of=None, weights=None, limit=20,
      reranker: Optional[AbstractReranker] = None, rerank_top_k=10,
  ) -> list[HybridCandidate]
  ```
  (signature is normative in spec §2 New Public Interfaces)
  - CTE (a) graph leg: `WITH RECURSIVE` from `seeds` concept_ids, depth ≤ 5,
    `validity @> $as_of` on EVERY hop (edges and versions), `depth` carried
    as a weighted signal (never a filter).
  - CTE (b) KNN leg: `embedding <=> $qvec` over versions with
    `validity @> $as_of` (strategy per TASK-2770: hood-restricted exact scan
    vs iterative ANN, cardinality threshold from the spike).
  - CTE (c) FTS leg: `ts_rank_cd` over `fts` with
    `websearch_to_tsquery($regconfig, $fts_terms)`, same validity predicate.
  - RRF fusion in SQL: `score = Σ w_leg / (60 + rank_leg)` (+ depth-decay
    term for the graph leg per `weights`); k=60 fixed (parity with
    `_RRF_K`, `pageindex/hybrid_search.py`).
  - Legs are optional: any subset of {embedding, fts_terms, seeds} may be
    given; ≥1 required (ValueError otherwise — mirror
    `HybridPageIndexSearch.search`'s guard).
  - `as_of=None` → `now()`; naive datetime → ValueError (TASK-2767 rule).
  - Python re-ranking step: build `SearchResult` docs reading FULL content
    (`body` or the file at `body_ref`), call
    `reranker.rerank(query_text, docs, top_n=rerank_top_k)`; on failure or
    NaN scores keep fused order (`_apply_reranker` semantics). `query_text`
    = `fts_terms` or a `query_text` kwarg — decide and document.
  - `HybridCandidate` model per spec §2 (concept_id, version_id, title,
    score, signals per leg, body_ref, evidence pairs from matched edges'
    `evidence_ref`).
- Tests: per-leg, fusion math, temporal transversality, rerank fallback,
  E2E ingest→retrieve.

**NOT in scope**: toolkit tools (TASK-2773), router seed computation (caller
provides seeds), reranker implementations (existing).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py` | MODIFY | `hybrid_retrieve` + SQL builder + `HybridCandidate` |
| `packages/ai-parrot/tests/knowledge/graphindex/test_hybrid_retrieve.py` | CREATE | live-gated leg/fusion/rerank tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.rerankers.abstract import AbstractReranker   # rerankers/abstract.py:35
from parrot.models.stores import SearchResult            # used by rerankers + pageindex _apply_reranker
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/rerankers/abstract.py:50
async def rerank(self, query: str, documents: list[SearchResult],
                 top_n: Optional[int] = None) -> list[RerankedDocument]
# CONTRACT: never raises on internal failure — returns inputs with
# rerank_score=NaN in original order; caller applies fallback.

# packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py — patterns to COPY (not import):
_RRF_K = 60
# _rrf_fuse: score += 1.0 / (k + rank + 1) per ranking
# _apply_reranker: builds SearchResult(id, content, metadata, score) docs;
#   maps RerankedDocument back via document.id; falls back to fused order on
#   exception or unmapped ids; result["source"] = "reranked"
# search(): raises ValueError when all signals disabled — mirror this guard.

# TASK-2767: as_of validity predicate; TASK-2770 artifact:
#   artifacts/logs/feat-520-oq3-spike.md — CTE order + ANN decisions (read it).
```

### Does NOT Exist
- ~~`hybrid_search` on this class~~ — the name is RESERVED by
  `PgVectorStore.hybrid_search` (`ai-parrot-embeddings/src/parrot/stores/postgres.py:1728`,
  SQLAlchemy, dense+ColBERT). This method is `hybrid_retrieve`. Do not import
  or call anything from `parrot.stores.postgres`.
- ~~BM25 in Postgres~~ — the FTS leg is `ts_rank_cd`, not BM25 (spec
  Non-Goals); do not add ParadeDB.
- ~~an LLM-walk leg~~ — pageindex's `_llm_rank` is NOT part of this design;
  the third leg here is the graph CTE.
- ~~reranker construction here~~ — the caller passes an `AbstractReranker`
  instance (factory wiring is TASK-2773's toolkit concern).

---

## Implementation Notes

### Pattern to Follow (one statement, sketch)
```sql
WITH RECURSIVE hood AS (
  SELECT concept_id, 0 AS depth FROM unnest($seeds::text[]) AS s(concept_id)
  UNION
  SELECT e.dst, h.depth + 1 FROM hood h
    JOIN graphindex.edges e ON e.src = h.concept_id AND e.validity @> $as_of
  WHERE h.depth < $max_depth
), knn AS (...ORDER BY embedding <=> $qvec LIMIT $k...),
   fts AS (...ts_rank_cd(fts, websearch_to_tsquery($reg, $terms))...),
   ranked AS (per-leg rank() OVER (...)),
fused AS (SELECT concept_id, version_id,
   sum(w / (60 + leg_rank)) + $depth_w * exp(-depth) AS score, ... GROUP BY ...)
SELECT ... ORDER BY score DESC LIMIT $limit;
```
(Exact shape is the implementer's — invariants: one statement, validity on
all legs, rank-based RRF, depth as signal.)

### Key Constraints
- `signals` dict on each candidate must expose per-leg contributions
  (debuggability + tests assert fusion math).
- Reading `body_ref` files: `asyncio.to_thread` or aiofiles — no blocking IO
  in the loop.
- Deterministic tie-break (score DESC, concept_id) for stable tests.

### References in Codebase
- Spec §3 Module 7; §4 hybrid tests; `HybridPageIndexSearch` throughout.

---

## Acceptance Criteria

- [ ] Single-statement execution verified (one `fetch` call; test asserts no
      N+1 across legs).
- [ ] Each leg works alone; ValueError with none (tests).
- [ ] `as_of` excludes repealed versions from ALL legs pre-fusion (test:
      a closed version reachable by KNN must not appear).
- [ ] RRF scores match the reference `Σ w/(60+rank)` computation (test).
- [ ] Rerank failure/NaN → fused order preserved (test with a stub reranker).
- [ ] `evidence` carries `(body_ref, byte_offset)` pairs from matched edges
      (test).
- [ ] E2E: ingest small corpus → seeds+embedding+terms → sensible top-k
      (integration test, live-gated).
- [ ] `ruff check` clean; zero SQLAlchemy.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_hybrid_retrieve.py
async def test_graph_leg_only(...); async def test_knn_leg_only(...)
async def test_fts_leg_only(...);  async def test_no_legs_raises(...)
async def test_rrf_fusion_math(...); async def test_as_of_transversal(...)
async def test_rerank_fallback(...); async def test_evidence_pairs(...)
async def test_e2e_ingest_then_retrieve(...)
```

---

## Agent Instructions

1. Read TASK-2770's spike artifact FIRST — it fixes CTE order and ANN usage.
2. Read spec §2 New Public Interfaces (signature is normative) and §3 Module 7.
3. Update index status; move to completed + note when done.

---

## Completion Note

Implemented `hybrid_retrieve` on `PostgresPersistence` with the normative
spec §2 signature, plus `HybridCandidate`. One SQL statement (one `fetch`
call, verified by `test_single_statement_execution` which monkeypatches
`asyncpg.Connection.fetch` and asserts a call count of 1) assembled
dynamically from three optional CTEs (graph/knn/fts), each included only
when its corresponding param is given, joined via `UNION` into a
`candidates` set, then LEFT-JOINed back for scoring.

**Unification decision** (not fully specified by the task — the graph
leg's "rank" needed a concrete definition): rather than a separate
depth-decay term, the graph leg's BFS depth order becomes an ordinal rank
(`row_number() OVER (ORDER BY depth ASC, concept_id ASC)`), so ALL THREE
legs share literally the same `Σ w_leg/(60+rank_leg)` RRF formula (spec's
own wording: "RRF fusion ... in SQL" — read as uniform across legs, with
depth acting as the graph leg's ranking signal rather than a bolted-on
multiplier). `test_rrf_fusion_math` asserts the exact formula.

**CTE order per TASK-2770**: when both `seeds` and `query_embedding` are
given, the KNN leg is restricted to the graph hood
(`nv.concept_id IN (SELECT concept_id FROM graph_leg)`) — the spike's
measured winner. `query_embedding` alone runs an unrestricted top-K.

**query_text decision** (task asked to "decide and document"):
`fts_terms` doubles as the re-ranking query text; the normative signature
has no separate `query_text` param, so reranking is skipped (fused order
returned) when a reranker is supplied without `fts_terms` — documented in
the method docstring.

**Bug found and fixed during testing** (worth flagging for future SQL
-builder code in this codebase): initially allocated the three weight
placeholders (`$N` for `w_graph`/`w_knn`/`w_fts`) unconditionally, but
only referenced them in the query text conditionally per active leg. An
allocated-but-never-referenced asyncpg parameter makes Postgres's prepare
step fail with `IndeterminateDatatypeError` ("could not determine data
type of parameter $N") — not a syntax error, so it only surfaced once
live-tested with a single-leg call. Fixed by moving weight-placeholder
allocation inside the same `if seeds:` / `if query_embedding:` /
`if fts_terms:` blocks that reference them, and added explicit `::float8`
/ `::int` casts throughout for parameters used only in arithmetic/LIMIT
contexts (same class of ambiguity).

Re-ranking copies `HybridPageIndexSearch._apply_reranker`'s fallback
semantics exactly: reads full `body_ref` content via `asyncio.to_thread`
(never blocks the loop), and falls back to fused order on either an
exception OR a NaN `rerank_score` (the `AbstractReranker` contract's own
internal-failure signal) — both paths covered by dedicated tests.

All 14 tests pass (no-legs ValueError, each leg alone, RRF fusion math
against the literal formula, `as_of` transversality across a version
close, naive-datetime rejection, evidence pairs from matched edges,
rerank success/failure/NaN-fallback, single-statement execution, E2E
ingest→retrieve). Ran the full `tests/knowledge/graphindex/` +
`test_postgres_store.py` + `test_extra_backends.py` suite: 806 passed, 4
pre-existing failures in `test_meta_ontology.py`/`test_projection.py`/
`test_schema.py` (EdgeKind enum-completeness checks) — confirmed
unrelated via `git diff` showing zero changes to `schema.py`/
`meta_ontology.py`/`projection.py` on this branch; not touched, not
fixed (no scope creep). `ruff check` clean; zero SQLAlchemy imports;
`parrot.stores.postgres` never referenced (grep-verified in the test).
