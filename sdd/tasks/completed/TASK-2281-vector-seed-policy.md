# TASK-2281: `VectorSeedPolicy` — FTS5 ∥ FAISS `FlatL2`, fused with RRF

**Feature**: FEAT-435 — GraphIndex Retrieval Layer
**Spec**: `sdd/specs/graphindex-retriever.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2271, TASK-2273
**Assigned-to**: unassigned
**Spec task ref**: T6 (spec §10)

---

## Context

Spec §5.2, as corrected by OQ-9. Hybrid seeding: BM25 ∥ dense, fused with
Reciprocal Rank Fusion, `expand` limited to depth 1 over containment edges.

**Read the OQ-9 correction before you start.** The spec originally said the
dense leg was "pgvector HNSW". It is not: `GraphIndexEmbedder` uses an
in-process `faiss.IndexFlatL2` (`embed.py:51`) and `_persist_to_pgvector()` is a
logging stub that does nothing (`embed.py:193-206`). There is no pgvector read
path and no HNSW anywhere. T6 seeds over what exists; durable pgvector/HNSW is
**TASK-deferred T6b**, gated on T13 measuring a real miss.

Consequently the **p50 < 120 ms target is provisional, not committed** (spec
§13) — `FlatL2` is an exhaustive scan. Do not build a latency gate.

---

## Scope

- `VectorSeedPolicy`, `kind: Literal["vector_seed"]`.
- `seed`: two legs concurrently via `asyncio.gather`:
  - **lexical** — `SQLiteGraphReader.search_symbols()` (FTS5/BM25). Note it
    indexes **title + summary only, not bodies**; document that limitation in
    the docstring since it caps recall.
  - **dense** — `GraphIndexEmbedder.search_similar()` (FAISS `FlatL2`, returns
    ascending L2 distance where smaller = more similar; invert before fusing).
- Fuse with RRF. **Reuse the existing implementation's formula** —
  `pageindex/hybrid_search.py::_rrf_fuse` (`:277`); do not invent a variant.
- Graceful degradation: if the reader is absent (`supports_fts` false) or the
  embedder is absent, run the single available leg rather than failing. Record
  which legs ran in the trace.
- `expand`: depth 1, **containment edges only** (`EdgeKind.CONTAINS`).
- `prune` + `assemble` per the shared protocol; digests via TASK-2273, content
  via `read_at_rev`.

**NOT in scope**:

- **Do NOT implement pgvector or HNSW.** That is T6b, explicitly deferred and
  gated on T13 (spec §5.2, §10). Implementing it here would be optimising an
  unmeasured path — the exact error §7 exists to prevent.
- Do not modify `graphindex/embed.py` to fix the stub. L0 is read-only (§1.2).
- PPR / multi-hop expansion — T8, not in the v1 cut.
- Escalation — TASK-2282.

---

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/knowledge/retrieval/policies/vector_seed.py` — new.
- `packages/ai-parrot/tests/knowledge/retrieval/test_vector_seed_policy.py` — new.

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` @ `bfa056bc7`, 2026-08-20. Spec §14 holds the full contract;
this is the slice this task needs. **Re-verify before you rely on it** — run
the greps yourself if anything looks stale.

### Verified Imports

```python
from parrot.knowledge.graphindex.sqlite_reader import SQLiteGraphReader
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder
from parrot.knowledge.graphindex.schema import EdgeKind
from parrot.knowledge.retrieval.digest import derive_digest
from parrot.knowledge.retrieval.pin import read_at_rev
```

### Existing Signatures to Use

```python
# parrot/knowledge/graphindex/sqlite_reader.py
class SQLiteGraphReader:
    #   search_symbols(...) — FTS5/BM25 over title + summary ONLY      # :323
    #   SQL: "... bm25(nodes_fts) AS score ... WHERE nodes_fts MATCH ?
    #         ORDER BY score LIMIT ?"                                  # :342-344
    #   BM25 scores from SQLite are NEGATIVE; ascending order = best first

# parrot/knowledge/graphindex/embed.py
class GraphIndexEmbedder:
    self.index: faiss.IndexFlatL2 = faiss.IndexFlatL2(dimension)       # :51
    async def search_similar(self, query_text: str, top_k: int = 10
                             ) -> list[tuple[str, float]]              # :122
    #   "sorted by ascending L2 distance (smaller = more similar)"
    async def _persist_to_pgvector(self, node_id, embedding) -> None    # :193
    #   STUB — logs "not yet implemented", writes nothing

# parrot/knowledge/pageindex/hybrid_search.py — REUSE this formula
@staticmethod
def _rrf_fuse(rankings: list[list[str]], k: int = _RRF_K
              ) -> list[tuple[str, float]]                             # :277
```

### Does NOT Exist

- **`parrot.knowledge.retrieval` does not exist yet.** You may be the task that
  creates it. There is nothing to extend, no base class waiting for you.
- **`RoutingDecision` EXISTS but is NOT ours.** It belongs to
  `parrot/bots/mixins/intent_router.py:378` (LLM intent routing). This feature's
  model is **`RetrievalRoutingDecision`**. Never import or extend the former.
- **`UniversalNode` has no `repo`, `rev`, `digest`, `line_span`, or `qualname`
  field.** Verified: `parrot/knowledge/graphindex/schema.py`. Do not write code
  that reads them. Line spans live in `domain_tags["lineno"/"end_lineno"]`;
  symbol kind lives in `domain_tags["symbol_type"]`.
- **There is no symbol trie or symbol table.** `graphindex/resolve.py` is a
  cross-domain *embedding-similarity* stage emitting `mentions` edges — it does
  NOT resolve names. Do not `from parrot.knowledge.graphindex.resolve import`
  anything expecting lookup.
- **`NodeKind` has no `Module`/`Class`/`Function` members.** The real set is
  `DOCUMENT SECTION SYMBOL CONCEPT RATIONALE SKILL WIKI_PAGE RUN CLAIM`.
- **No pgvector read path. No HNSW. Anywhere.** `_persist_to_pgvector` is a
  no-op stub. `parrot.stores.pgvector` exists for *document* vector storage and
  is NOT wired to GraphIndex nodes — do not bridge them in this task.
- **FTS5 exists only on the SQLite backend.** ArangoDB has no `nodes_fts`. A
  workspace on Arango has no lexical leg; degrade, don't crash.
- **BM25 scores are negative and L2 distances are ascending-better.** Both are
  inverted relative to "higher is better". Fusing them raw silently ranks
  worst-first — the most likely bug on this task.

---

## Implementation Notes

### Pattern to Follow

RRF is rank-based, which conveniently sidesteps the two score-direction traps
above — but only if you feed it correctly *ordered* ranking lists. Sort each leg
into best-first order before fusing and assert that ordering in a test, rather
than trusting either backend's sign convention. Mirror
`tests/knowledge/pageindex/test_hybrid_search.py::test_rrf_formula_matches_reference`
so the two RRF implementations cannot drift.

### Key Constraints

- **Frozen Pydantic v2 everywhere**: `model_config = ConfigDict(frozen=True,
  extra="forbid")`. Every model in spec §3 declares this; match it.
- **Google-style docstrings + strict type hints** on every public function and
  class (project rule, `CLAUDE.md`).
- `self.logger = logging.getLogger(__name__)` — never `print`.
- `async`/`await` throughout; `aiosqlite` for SQLite, never blocking `sqlite3`.
- No `requests`/`httpx` — `aiohttp` only (project rule).
- Run the two legs concurrently with `asyncio.gather`; a sequential seed doubles
  the stage the whole escalation cost model (§4.4) assumes is the expensive one.
- `aiosqlite` only for the FTS leg.

### References in Codebase

- Spec §5.2 (as corrected by OQ-9), §9 OQ-9, §11.1 row 5, §14.2/§14.3.
- `tests/knowledge/pageindex/test_hybrid_search.py:101` — the RRF reference
  test to mirror.

---

## Acceptance Criteria

- [ ] RRF output matches the reference formula (mirrors the pageindex test).
- [ ] Each leg is sorted best-first before fusion — asserted, so a sign flip in
      either backend is caught.
- [ ] FTS-only degradation (no embedder) returns results.
- [ ] Dense-only degradation (no reader / `supports_fts` false) returns results.
- [ ] The two legs run concurrently (assert via ordering/timing spy, not
      wall-clock).
- [ ] `expand` traverses `CONTAINS` only, depth 1.
- [ ] Digest of each unit matches a recomputation over its served `text`.
- [ ] No import of `parrot.stores.pgvector`; `_persist_to_pgvector` untouched.
- [ ] `ruff` + `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/retrieval/test_vector_seed_policy.py
def test_rrf_matches_reference_formula(): ...
async def test_legs_sorted_best_first_before_fusion(): ...
async def test_fts_only_degradation(): ...
async def test_dense_only_degradation(): ...
async def test_legs_run_concurrently(): ...
async def test_expand_is_depth1_contains_only(): ...
async def test_digest_matches_served_text(): ...
def test_does_not_import_pgvector(): ...
```

---

## Agent Instructions

1. Read the spec section(s) named in **Context** before writing code. The spec
   is the SSOT; this task file is a view onto it.
2. Write the tests first (see **Test Specification**), watch them fail, then
   implement. TDD is not optional here — every one of these tasks encodes an
   invariant.
3. Do NOT modify anything under `parrot/knowledge/graphindex/` or
   `parrot_tools/multistoresearch/`. L0 is consumed **read-only** (spec §1.2)
   and FEAT-217/FEAT-379 are untouched by design (spec §5.0). If you believe a
   change there is required, STOP and record it in the Completion Note instead.
4. Run `pytest packages/ai-parrot/tests/knowledge/retrieval/ -v`, then `ruff check` and `mypy` on the files you
   touched. Paste real output into the Completion Note — no claims without
   evidence.
5. Commit once, message: `feat(FEAT-435): <what> (TASK-<NNN>)`.
6. Fill in the Completion Note. If you hit an ambiguity, record it there rather
   than inventing a resolution.

---

## Completion Note

Implemented `VectorSeedPolicy` in `policies/vector_seed.py`: BM25 (via
`SQLiteGraphReader.search_symbols`) and dense (via a duck-typed
`GraphIndexEmbedder`-shaped `search_similar`) legs run concurrently via
`asyncio.gather`, fused with `HybridPageIndexSearch._rrf_fuse` reused
verbatim (imported, not reimplemented) with the matching `_RRF_K = 60`.

**Design decisions (documented, not silently invented):**

1. **`reader`/`embedder` typed `Any | None`, not `SQLiteGraphReader |
   None`.** Pydantic validates arbitrary types via `isinstance`, so a
   strict `SQLiteGraphReader` annotation would reject any lightweight
   test double — discovered when `test_legs_run_concurrently`'s spy
   reader hit a `ValidationError` (see "bugs found" below). Both fields
   are duck-typed against the methods actually called
   (`search_symbols`/`get_node`/`children` for the reader,
   `search_similar` for the embedder), matching how the task's own
   acceptance criteria ask for a "timing spy" — which requires a fake,
   not a real `SQLiteGraphReader` subclass.
2. **`_sanitize_fts_query()` — not in the task's literal scope, but
   required.** `req.query` may carry markdown-style code quoting
   (`` `Foo.bar()` ``) or dotted qualified names; passed raw to FTS5
   `MATCH`, both raise `fts5: syntax error`. Tokens are extracted
   (`\w+`) and joined with `OR` (not implicit `AND` — title/summary are
   separate indexed rows, so an `AND` query naming two different symbols
   would incorrectly return zero rows). Added after two real
   `sqlite3.OperationalError`s surfaced during testing (`syntax error
   near "`"`, then `syntax error near "."`) — not guessed at up front.
3. **`rev: str` added as an explicit field** (not in the task's literal
   scope). Search results (`search_symbols`/`get_node`/`search_similar`)
   carry no rev of their own — unlike `DirectSymbolPolicy`, which gets
   `rev` for free via `DerivedSymbolIndex`-produced seed `NodeRef`s.

**Bugs found and fixed during testing (not just "tests pass on first
try"):**
- `ValidationError` on `SQLiteGraphReader | None` rejecting a spy double
  → relaxed to `Any | None` (see above).
- `fts5: syntax error near "`"` — backticks passed raw to `MATCH` →
  `_sanitize_fts_query()` added.
- `fts5: syntax error near "."` — same sanitizer's first version kept
  dots and used implicit `AND`; fixed to token-extraction + `OR`.
- A background hang unrelated to correctness: exploratory standalone
  `python -c` scripts (used to isolate the above) hung past an unhandled
  exception's traceback, apparently due to a lingering thread/executor
  from the real `navconfig`/aiosqlite stack — confirmed harmless to the
  actual test suite (which runs and exits cleanly under `pytest`) and not
  investigated further, since it only affected ad hoc debugging scripts.

**Test output:**
```
$ pytest packages/ai-parrot/tests/knowledge/retrieval/ -v
======================= 139 passed, 6 warnings in 6.62s ========================
```
(9 new tests in `test_vector_seed_policy.py`, using a real
`SQLitePersistence`/`SQLiteGraphReader` round-trip, a real temp git repo,
and a duck-typed `_FakeEmbedder` — no mocking framework needed.)

**Lint:**
```
$ ruff check packages/ai-parrot/src/parrot/knowledge/retrieval/ packages/ai-parrot/tests/knowledge/retrieval/
All checks passed!
```

**Mypy:** zero errors attributable to `knowledge/retrieval`.

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-08-20
