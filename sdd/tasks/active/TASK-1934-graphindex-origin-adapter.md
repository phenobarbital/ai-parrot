# TASK-1934: `GraphIndexOrigin` adapter (+ optional FTS leg via SQLite reader)

**Feature**: FEAT-379 — MultiStoreSearch Toolkit with PageIndex, GraphIndex & ParrotWiki Origins
**Spec**: `sdd/specs/multistoresearchtool-parrotwiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1932
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5: the GraphIndex origin adapter over the 4-phase
graph retrieval pipeline (seed → expand → community annotation → assembly).
Resolved decision: the adapter is FTS-capable **only when configured with a
`SQLiteGraphReader`** — its `search_symbols` is an async FTS5/BM25
lexical search; without a reader, `supports_fts=False`.

---

## Scope

- Implement `GraphIndexOrigin(SearchOrigin)` in
  `parrot_tools/multistoresearch/origins/graphindex.py`.
- Constructor: `retriever` (`GraphExpandedRetriever` instance),
  optional `reader` (`SQLiteGraphReader` instance), `name: str = "graphindex"`,
  `description` (default explains graph retrieval + community context),
  optional `timeout`, optional `seed_top_k` pass-through.
- `search`: `await retriever.search(query, seed_top_k=...)` →
  `GraphRetrievalResult`; flatten its scored nodes into ordered
  `list[OriginHit]` (read `GraphRetrievalResult` / `ScoredNode` fields in the
  source before implementing — see contract).
- `supports_fts` = `reader is not None`.
- `fts_search`: `await reader.search_symbols(query, limit=k)`; **FTS5 BM25
  scores are NEGATIVE, ascending = best** — preserve the reader's order for
  `native_rank` and carry the raw score into `OriginHit.score` (document the
  sign convention in metadata or docstring).
- Unit tests: flattening, reader/no-reader FTS capability, negative-score
  rank normalization.

**NOT in scope**: toolkit integration (TASK-1936); any change under
`parrot/knowledge/graphindex/` (read-only consumption); querying `nodes_fts`
SQL directly.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/graphindex.py` | CREATE | Adapter |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py` | MODIFY | Export `GraphIndexOrigin` |
| `packages/ai-parrot-tools/tests/multistoresearch/test_graphindex_origin.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models import SearchOriginKind, OriginHit                # TASK-1930
from parrot_tools.multistoresearch.origins.base import SearchOrigin  # TASK-1932
# Backends passed as instances; lazy/TYPE_CHECKING imports only:
# parrot.knowledge.graphindex.retriever.GraphExpandedRetriever
# parrot.knowledge.graphindex.sqlite_reader.SQLiteGraphReader
```

> **Contract correction (verified 2026-07-27 during TASK-1934 implementation):**
> the reader class is actually named **`SQLiteGraphReader`**
> (`packages/ai-parrot/src/parrot/knowledge/graphindex/sqlite_reader.py:47`,
> re-exported from `parrot.knowledge.graphindex.__init__`), not
> `SQLiteGraphReader` as originally written in this task and in the
> spec. `search_symbols` is unaffected — same signature, same file, same
> line (320). All other Codebase Contract references below are updated to
> the correct name.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py
class ExpansionConfig(BaseModel):    # line 49
class BudgetConfig(BaseModel):       # line 80
class ScoredNode(BaseModel):         # line 94  — read fields before flattening
class GraphRetrievalResult(BaseModel):  # line 136 — read fields before flattening
class GraphExpandedRetriever:        # line 168
    async def search(self, query: str, seed_top_k: int = 10,
                     expansion: Optional[ExpansionConfig] = None,
                     budget: Optional[BudgetConfig] = None) -> GraphRetrievalResult  # line 658

# packages/ai-parrot/src/parrot/knowledge/graphindex/sqlite_reader.py
class SQLiteGraphReader:  # exact class-name spelling: verify at the top of the file
    async def search_symbols(self, query: str, *, limit: int = 20) -> list[dict]  # line 320
    # FTS5/BM25 over title+summary; auto-load()s; scores NEGATIVE, ascending = best.
    # Result dict keys: node_id, kind, title, source_uri, summary, score, domain_tags
```

### Does NOT Exist
- ~~`GraphExpandedRetriever.fts_search`~~ / any public FTS method on the retriever — FTS goes through the reader's `search_symbols` ONLY.
- ~~direct SQL on `nodes_fts`~~ — internal table (`persist_sqlite.py:242`); never query it from the adapter.
- ~~`GraphIndexOrigin`~~ — does not exist yet; THIS task creates it.
- ~~positive/normalized FTS scores~~ — `search_symbols` returns raw negative BM25 scores; do not assume 0..1.

---

## Implementation Notes

### Key Constraints
- `limit` is keyword-only in `search_symbols` — call `search_symbols(query, limit=k)`.
- `native_rank` reflects the backend's returned order (already best-first in
  both legs).
- Adapters raise on backend failure; toolkit isolates (TASK-1936).
- Class docstring explains graph retrieval and the reader-dependent FTS
  capability (surfaces via `list_search_origins`).

### References in Codebase
- Spec §2 adapter table (GraphIndex row) + §8 resolved question on FTS leg.
- `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` — existing agent-facing GraphIndex toolkit, useful for how retriever/reader instances are typically constructed and held.

---

## Acceptance Criteria

- [ ] `GraphIndexOrigin(retriever=...)` → `supports_fts is False`; with `reader=` → `True`.
- [ ] `search` flattens `GraphRetrievalResult` into ordered `OriginHit`s (`origin_kind == SearchOriginKind.GRAPHINDEX`, 1-based `native_rank`).
- [ ] `fts_search` maps `search_symbols` rows to `OriginHit`s preserving best-first order despite negative scores.
- [ ] `fts_search` without a reader raises `NotImplementedError` (contract default).
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/multistoresearch/test_graphindex_origin.py -v`
- [ ] `ruff check` clean on the new file.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/multistoresearch/test_graphindex_origin.py
import pytest
from parrot.models import SearchOriginKind
from parrot_tools.multistoresearch.origins import GraphIndexOrigin

class FakeReader:
    async def search_symbols(self, query, *, limit=20):
        return [
            {"node_id": "a", "kind": "class", "title": "Best", "source_uri": "x",
             "summary": "s", "score": -9.1, "domain_tags": {}},
            {"node_id": "b", "kind": "class", "title": "Second", "source_uri": "y",
             "summary": "s", "score": -3.2, "domain_tags": {}},
        ]

async def test_fts_capability_reflects_reader():
    assert GraphIndexOrigin(retriever=object()).supports_fts is False
    assert GraphIndexOrigin(retriever=object(), reader=FakeReader()).supports_fts is True

async def test_fts_preserves_reader_order():
    origin = GraphIndexOrigin(retriever=object(), reader=FakeReader())
    hits = await origin.fts_search("q", k=5)
    assert [h.native_rank for h in hits] == [1, 2]
    assert hits[0].content.startswith("Best") or "Best" in hits[0].content

async def test_search_flattens_retrieval_result():
    # build a fake retriever returning a GraphRetrievalResult-shaped object
    ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1932 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code (read `GraphRetrievalResult`/`ScoredNode` fields and confirm the reader class name)
4. **Update status** in `sdd/tasks/index/multistoresearchtool-parrotwiki.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
