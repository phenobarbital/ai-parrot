# TASK-1936: `MultiStoreSearchToolkit` core — 4 tools, isolation, grouped+merged payload

**Feature**: FEAT-379 — MultiStoreSearch Toolkit with PageIndex, GraphIndex & ParrotWiki Origins
**Spec**: `sdd/specs/multistoresearchtool-parrotwiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1932, TASK-1933, TASK-1934, TASK-1935
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 7 — the toolkit itself. `AbstractToolkit`
auto-converts public async methods into agent tools (name = method name,
description = docstring), so the four tool methods' docstrings are the LLM's
tool descriptions: write them for the LLM.

---

## Scope

- Implement `MultiStoreSearchToolkit(AbstractToolkit)` in
  `parrot_tools/multistoresearch/toolkit.py`:
  `__init__(origins: list[SearchOrigin], k: int = 10, k_per_origin: int = 20,
  default_timeout: float = 30.0, bm25_weights: Optional[dict[str, float]] = None, **kwargs)`.
- **`store_search(query, k=None) -> MultiSearchResponse`**: per-origin
  coroutines wrapped in `asyncio.wait_for(origin.search(...),
  timeout=origin.timeout or default_timeout)`, gathered with
  `return_exceptions=True`. Each origin yields an `OriginSection`
  (status `"ok"|"error"|"timeout"`, note on failure, native-order hits, the
  origin's `description`). Merged block: dedup (ID then content-hash) + BM25
  rerank over ALL section hits → `merged_top_k`. `notes` includes the
  score-comparability caveat.
- **`batch_search(queries, k=None) -> list[MultiSearchResponse]`**: N queries
  × M origins in ONE `asyncio.gather` (resolved decision — no
  `asyncio.to_thread`); per-query responses in `store_search` shape; empty
  list → empty result.
- **`fts_search(query, k=None) -> MultiSearchResponse`**: runs only origins
  with `supports_fts=True` via `origin.fts_search`; non-capable enabled
  origins appear as sections with status `"skipped"` + reason; zero capable
  origins → notes-only response.
- **`list_search_origins() -> list[dict]`**: static config only (resolved
  decision): name, kind, description, supports_fts, timeout, extra settings
  (e.g. PageIndex mode).
- Lift BM25 rerank + dedup from the legacy tool
  (`_legacy_tool.py`, formerly `multistoresearch.py`: `_rerank_with_bm25`
  line 201, `_deduplicate_results` line 351) into private helpers adapted to
  `OriginHit` (private `_`-methods are NOT exposed as tools).
- Satisfy the `MultiSearch` protocol: `async def search(self, query, k=None,
  **kwargs)` delegating to `store_search`, listed in `exclude_tools` so it is
  NOT exposed as an agent tool.
- No-origins case: structured "no origins configured" response, not an exception.
- Unit tests + toolkit tool-generation test.

**NOT in scope**: registry entry & old-tool deletion (TASK-1937); docs (TASK-1938).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py` | CREATE | Toolkit |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/__init__.py` | MODIFY | Export `MultiStoreSearchToolkit` (keep legacy re-export until TASK-1937) |
| `packages/ai-parrot-tools/tests/multistoresearch/test_toolkit.py` | CREATE | Unit tests |
| `packages/ai-parrot-tools/tests/multistoresearch/test_toolkit_tools_generated.py` | CREATE | `get_tools()` surface test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit   # packages/ai-parrot/src/parrot/tools/toolkit.py:207
from parrot.models import (SearchOriginKind, OriginHit, OriginSection,
                           MultiSearchResponse, MultiSearch)  # TASK-1930
from parrot_tools.multistoresearch.origins import (SearchOrigin, VectorStoreOrigin,
    PageIndexOrigin, GraphIndexOrigin, ParrotWikiOrigin)      # TASK-1932..1935
from rank_bm25 import BM25Okapi   # existing dep — usage reference: _legacy_tool.py:255
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                      # line 207
    # auto-converts PUBLIC ASYNC methods into tools (name=method, description=docstring)
    exclude_tools: tuple[str, ...] = ()          # class attr — add "search" here
    tool_prefix: Optional[str] = None            # leave None (tool names = method names)
    confirming_tools: frozenset = frozenset()    # not needed here
    # read get_tools() in the file before writing the surface test

# parrot_tools/multistoresearch/_legacy_tool.py (moved by TASK-1932; original multistoresearch.py)
    def _rerank_with_bm25(self, query, results) -> List[SearchResult]   # line 201 — LIFT & adapt to OriginHit
    def _deduplicate_results(self, results, similarity_threshold=0.95)  # line 351 — LIFT & adapt
    # gather pattern with return_exceptions=True: line 319
```

### Does NOT Exist
- ~~cross-origin comparable scores~~ — vector distances (lower=better), wiki FTS ranks, negative graph BM25 are NOT comparable; the merged block ranks by BM25-over-content (+ optional per-origin weights), NEVER by raw score sorting across origins.
- ~~`asyncio.to_thread` anywhere in this task~~ — forbidden by decision (spec acceptance criterion greps for it).
- ~~`MultiStoreSearchToolkit`~~ — does not exist yet; THIS task creates it.
- ~~automatic tool exposure of private methods~~ — only PUBLIC async methods become tools; helpers must be `_`-prefixed or in `exclude_tools`.

---

## Implementation Notes

### Key Constraints
- Grouped sections keep native order AND cross-origin duplicates (dedup is
  merged-block-only — spec §7).
- `k_per_origin` is what each origin is asked for; `k` caps `merged_top_k`.
- Timeout: `asyncio.wait_for` per origin; `TimeoutError` → status "timeout".
  Any other exception → status "error" with `repr(exc)` in `note`.
- Tool docstrings (LLM-facing) must explain: what each origin kind is, that
  sections are native-ranked, and that `merged_top_k` is BM25-merged.
- Check how other toolkits in `parrot_tools` structure `__init__` kwargs
  (e.g. `parrot_tools/graphindex/toolkit.py`) for constructor conventions.

### References in Codebase
- Spec §2 Overview + Data Models — authoritative payload semantics.
- `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` — existing `AbstractToolkit` subclass in the same package (style reference).

---

## Acceptance Criteria

- [ ] `get_tools()` exposes exactly: `store_search`, `batch_search`, `fts_search`, `list_search_origins` (and NOT `search`).
- [ ] `isinstance(toolkit, MultiSearch)` is True.
- [ ] `store_search` returns grouped sections (one per enabled origin, native order, description present) + BM25-merged deduped `merged_top_k`.
- [ ] Slow origin → its section status `"timeout"`, other origins unaffected (test with 0.05s timeout override).
- [ ] `fts_search` skips non-capable origins with status `"skipped"` + reason; zero-capable case returns notes-only response.
- [ ] `batch_search([])` → `[]`; `batch_search` uses a single gather (N×M tasks).
- [ ] No origins configured → structured message, no exception.
- [ ] `grep -rn "to_thread" packages/ai-parrot-tools/src/parrot_tools/multistoresearch/` → only the sanctioned executor wrap in `origins/pageindex.py` (which uses `run_in_executor`, not `to_thread`) — i.e. no matches.
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/multistoresearch/ -v`
- [ ] `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/multistoresearch/test_toolkit.py
import asyncio
import pytest
from parrot.models import MultiSearch, SearchOriginKind, OriginHit
from parrot_tools.multistoresearch import MultiStoreSearchToolkit
from parrot_tools.multistoresearch.origins.base import SearchOrigin

def make_origin(name, hits, supports_fts=False, delay=0.0):
    class _O(SearchOrigin):
        ...  # name/kind/description/supports_fts wired; search sleeps `delay` then returns hits
    return _O()

async def test_store_search_grouped_and_merged():
    tk = MultiStoreSearchToolkit(origins=[make_origin("a", ...), make_origin("b", ...)])
    resp = await tk.store_search("query")
    assert {s.origin for s in resp.sections} == {"a", "b"}
    assert resp.merged_top_k and resp.notes

async def test_timeout_isolated():
    tk = MultiStoreSearchToolkit(
        origins=[make_origin("slow", ..., delay=1.0), make_origin("fast", ...)],
        default_timeout=0.05)
    resp = await tk.store_search("q")
    by = {s.origin: s for s in resp.sections}
    assert by["slow"].status == "timeout" and by["fast"].status == "ok"

async def test_protocol_satisfied():
    tk = MultiStoreSearchToolkit(origins=[])
    assert isinstance(tk, MultiSearch)

async def test_fts_skips_non_capable():
    tk = MultiStoreSearchToolkit(origins=[make_origin("vec", ...),
                                          make_origin("wiki", ..., supports_fts=True)])
    resp = await tk.fts_search("q")
    by = {s.origin: s for s in resp.sections}
    assert by["vec"].status == "skipped" and by["wiki"].status == "ok"
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1932..1935 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code (read `AbstractToolkit.get_tools()` and the tool-generation machinery around line 207 first)
4. **Update status** in `sdd/tasks/index/multistoresearchtool-parrotwiki.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-07-27
**Notes**: Implemented `MultiStoreSearchToolkit(AbstractToolkit)` with
`store_search`/`batch_search`/`fts_search`/`list_search_origins`
(`search` excluded from tool generation via `exclude_tools` and used to
satisfy `MultiSearch`). Per-origin isolation via
`asyncio.wait_for(..., timeout=origin.timeout or default_timeout)` +
`asyncio.gather(..., return_exceptions=True)`; timeouts → status
`"timeout"`, other exceptions → status `"error"` with `repr(exc)`;
FTS-incapable origins → status `"skipped"` without ever being called.
`batch_search` dispatches the full N×M origin-call plan through exactly
ONE `asyncio.gather` (verified: `grep -rn to_thread` finds only a
docstring mention in `pageindex.py`, no actual usage anywhere in the
package). BM25 rerank + ID/content-hash dedup lifted from
`_legacy_tool.py` and adapted to `OriginHit` — origin-native scores are
left untouched (never blended into the ranking), only the merged
block's ORDER is BM25-derived, matching the spec's
non-comparable-scores decision. 26 new tests (16 toolkit + 2
tool-generation, plus reruns of the 8 pre-existing adapter/origin
tests) — full `multistoresearch/` suite is 50 tests, all passing;
`ruff check` clean.

**Deviations from spec**: Dropped the `bm25s`-then-force-fallback dead
code path present in the legacy tool (`_legacy_tool.py:224-253`, whose
own `try` block deliberately raised to always fall through to
`rank_bm25`) — the spec's External Dependencies section explicitly
allows "keep optional or drop the dead path"; `rank_bm25` is used
directly. No other deviation.
