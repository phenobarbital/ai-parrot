# TASK-2642: Graph-backed search_code / related_code with mode and grep degradation

**Feature**: FEAT-484 — ReadOnlyRepoToolkit — Safe Repo Grounding for Any Client
**Spec**: `sdd/specs/readonly-repo-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2639, TASK-2641
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 4** (search half) and §8 **Q2**.

This is the task that makes FEAT-484 worth building. Spec §1 frames the whole
feature around it: *"the gap is not 'we need a grep tool'. It is: a read-only,
cwd-confined toolkit that **prefers the existing code graph over grep**."*

The measured basis, from spec §1: `grep -rn` for one symbol returned 23 hits
including duplicates from `build/lib.linux-x86_64-cpython-311/`. The same query
against the wiki plane returned **12 ranked, deduplicated, build-artifact-free
results in ~592 tokens**. That delta is the feature.

Three things make this task the largest in the feature:

1. **Result mapping is not a rename.** `WikiSearchResult` and `RepoSearchHit` have
   genuinely different shapes and the field names do not line up — see the contract
   below. This is the single most likely place to hallucinate.
2. **Degradation must be honest.** When the plane is missing, `search_code` serves
   a `grep_files` result with `degraded=True` and a reason *in the payload the model
   sees*, plus a logged warning. Spec §7: "never silent". A silently-grep-backed
   `search_code` would make the feature's central claim untrue at runtime.
3. **`mode` is now a tool argument** (§8 Q2, resolved 2026-08-31 — this **overrides**
   the question's original "constructor-only" proposal). With no embedder shipped,
   `vector` and `combined` must degrade to lexical rather than fail.

---

## Scope

- Add to `ReadOnlyRepoToolkit`:
  - `async def search_code(query, top_k=12, mode=None) -> RepoSearchResult`
  - `async def related_code(page_id) -> RepoSearchResult`
- Lazily open the plane once per toolkit instance via TASK-2641's `open_plane()`,
  caching both the store and the failure reason. Honour a `wiki_store` passed to
  the constructor (skip resolution entirely when one is injected — this is what
  makes the tests fast and hermetic).
- Query `WikiCombinedSearch` in the caller's mode; pack with `pack_results` under
  `search_budget_tokens`; map to `RepoSearchHit` / `RepoSearchResult`.
- `related_code`: follow typed edges via `store.neighbors(page_id)`.
- **Degrade to `grep_files`** (TASK-2639) with `degraded=True`, a populated
  `degraded_reason`, and `self.logger.warning(...)` on: no plane, unbuilt plane, or
  any exception from the query path.
- Add `SearchCodeInput` / `RelatedCodeInput` schemas exposing `mode` as a
  `Literal["lexical", "vector", "combined"]`.
- Write unit tests in `test_search_code.py`.

### Behavior detail

- `mode=None` → use `self._default_search_mode` (constructor, default `"lexical"`).
- `top_k` clamped to `self._max_search_hits`.
- `total_tokens` = `packed.tokens_used`; must be `<= search_budget_tokens`.
- The happy path must spawn **no** grep subprocess. A test asserts this by
  monkeypatching `_run_argv` to fail loudly.
- `degraded=True` is set **only** by the fallback path here — a direct
  `grep_files` call still returns `degraded=False` (TASK-2639's contract).

**NOT in scope**:
- Wiring an embedder. Spec §8 Q4: lexical only. `vector`/`combined` are
  accepted-and-degraded values, **not** new capability. Do not add an embedder
  parameter, do not look one up.
- Building or refreshing the plane (spec §1 Non-Goals).
- `resolve_plane_root` / `open_plane` themselves → TASK-2641, already done.
- `web_search` → TASK-2643. Docs → TASK-2643.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repo/graph_search.py` | MODIFY | Add result mapping helpers |
| `packages/ai-parrot/src/parrot/tools/repo/toolkit.py` | MODIFY | Add `search_code`, `related_code`, `_plane()` |
| `packages/ai-parrot/src/parrot/tools/repo/schemas.py` | MODIFY | Add `SearchCodeInput`, `RelatedCodeInput` |
| `packages/ai-parrot/tests/tools/repo/test_search_code.py` | CREATE | Unit tests |
| `packages/ai-parrot/tests/tools/repo/conftest.py` | MODIFY | Add `stub_wiki_store` fixtures |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` on 2026-08-31 **by reading the source files**. The spec's
> §6 claim about `search()` modes needed correcting — see the note below.

### Verified Imports

```python
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.search import WikiCombinedSearch     # wiki/search.py:32
from parrot.knowledge.wiki.context import pack_results          # wiki/context.py:203
from parrot.tools.decorators import tool_schema                 # tools/decorators.py:39
from parrot.tools.repo.graph_search import open_plane           # TASK-2641
from parrot.tools.repo.models import (                          # TASK-2637
    RepoSearchHit, RepoSearchResult,
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/search.py
class WikiCombinedSearch:                                            # line 32
    def __init__(
        self,
        pageindex_toolkit: Any,        # pass None on the store path
        graphindex_toolkit: Any,       # pass None on the store path
        default_weights: Optional[dict[str, float]] = None,
        store: Optional[BaseWikiStore] = None,     # ← pass YOUR store here
        embedder: Optional[Callable[[str], Awaitable[list[float]]]] = None,
        normalize_store_rows: bool = True,
    ) -> None: ...                                                   # line 46

    async def search(
        self,
        query: str,
        mode: str = "combined",
        top_k: int = 10,
        tree_name: Optional[str] = None,
        weights: Optional[dict[str, float]] = None,
        include_archived: bool = False,
    ) -> list[WikiSearchResult]: ...                                 # line 91
```

> **CORRECTION to spec §6 — read this carefully.** The *class-level* `search()`
> docstring (`search.py:110`) says modes are `"combined" | "pageindex" |
> "graphindex"`. That docstring is **stale/legacy-focused**. The store path —
> which is what you use, because you pass `store=` — is `_search_store`
> (`search.py:150`), and its **verified body at `search.py:174-176`** is:
> ```python
> want_lexical = mode in ("combined", "lexical", "pageindex")
> want_vector  = mode in ("combined", "vector", "graphindex")
> ```
> So `"lexical"` / `"vector"` / `"combined"` **are** the correct values, exactly as
> the spec's §2 and §8 Q2 assume. `pageindex`/`graphindex` are legacy aliases.
>
> **And the §8 Q2 degradation is free**, verified at `search.py:202`:
> ```python
> if want_vector and self._embedder is not None:      # line 202
> ```
> With `embedder=None`, the vector leg is **skipped**, and `search.py:227-230`
> then gives the lexical leg full weight:
> ```python
> if lexical_results and not vector_results:
>     lex_weight = 1.0
> ```
> So `mode="vector"` with no embedder yields **empty** results (no lexical leg
> requested), while `mode="combined"` yields **lexical-only** results. Handle
> `mode="vector"` explicitly: with no embedder it would return nothing, so map it
> to lexical and say so in `degraded_reason`, rather than returning an empty list.

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/models.py:258
class WikiSearchResult(BaseModel):
    node_id: str      # line 275 — stable page identifier ("concept_id")
    title: str        # line 276 — human-readable page/node title
    score: float      # line 277 — normalised, ge=0.0 le=1.0
    source: str       # line 283 — "lexical" | "vector" | "pageindex" | "graphindex"
    snippet: str      # short excerpt/summary from the page content
    category: ...     # Optional WikiPageCategory
    token_count: int  # token cost of reading the FULL page body

# packages/ai-parrot/src/parrot/knowledge/wiki/context.py:112
class PackedContext(BaseModel):
    text: str = ""                 # line 125 — compact context block
    stubs: list[dict[str, Any]]    # line 126 — id, title, lead, score, token cost
    tokens_used: int = 0           # line 127
    results_packed: int = 0        # line 128
    total_available: int = 0       # line 129
    truncated: bool = False        # line 130

def pack_results(                                                    # line 203
    results: Iterable[Any],
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
) -> PackedContext: ...
# Consumes results in RANKED ORDER; stops when the next stub would exceed
# budget_tokens; skips duplicate ids. It is SYNC — do not await it.

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore:
    async def search_fts(self, query, category=None, limit=10)       # line 1147
    async def search_vector(self, embedding, limit=10)               # line 1195
    async def neighbors(                                             # line 1237
        self,
        concept_id: str,
        rel: Optional[str] = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]: ...

# packages/ai-parrot/src/parrot/tools/repo/toolkit.py  (earlier tasks)
class ReadOnlyRepoToolkit(AbstractToolkit):
    self._wiki_store: Optional[object]     # injected store, or None
    self._wiki_name: str
    self._default_search_mode: Literal["lexical", "vector", "combined"]
    self._max_search_hits: int
    self._search_budget_tokens: int
    self.logger: logging.Logger
    async def grep_files(self, pattern: str, glob: str = "") -> ...  # TASK-2639
    async def _run_argv(self, argv, *, timeout=None) -> dict         # TASK-2639
```

### CRITICAL — the field mapping (this is the hallucination trap)

`WikiSearchResult` and `RepoSearchHit` do **not** share field names. Map explicitly:

| `RepoSearchHit` (spec §2) | Source | Note |
|---|---|---|
| `page_id` | `WikiSearchResult.node_id` | **not** `.page_id` — that field does not exist |
| `path` | `WikiSearchResult.title` | page titles are path-shaped (`dir:pkg`, `file:...`) |
| `summary` | `WikiSearchResult.snippet` | **not** `.summary` — that field does not exist |
| `outline` | *not available from search* | leave `[]`; an API outline needs a page **read**, which is out of scope. Do **not** invent a source for it. |
| `score` | `WikiSearchResult.score` | direct |
| `approx_tokens` | `WikiSearchResult.token_count` | **not** `.approx_tokens` |

### Does NOT Exist

- ~~`WikiSearchResult.page_id`~~ / ~~`.path`~~ / ~~`.summary`~~ / ~~`.outline`~~ /
  ~~`.approx_tokens`~~ — **none of these exist.** See the mapping table above. This
  is the #1 hallucination risk in this task.
- ~~`WikiCombinedSearch.search()` being sync~~ — it is `async`. Await it.
- ~~`pack_results()` being async~~ — it is **sync** (`context.py:203`). Do not await it.
- ~~`PackedContext.hits`~~ / ~~`.results`~~ — the fields are `stubs`, `text`,
  `tokens_used`, `results_packed`, `total_available`, `truncated`.
- ~~`WikiCombinedSearch` accepting `store` as the first positional arg~~ — the
  first two positional params are `pageindex_toolkit` and `graphindex_toolkit`.
  Pass `store=` as a **keyword**, with the first two as `None`.
- ~~an embedder existing anywhere to pass~~ — none is wired (spec §6). Leave
  `embedder` unset.
- ~~`store.neighbors` taking a `page_id=` keyword~~ — the parameter is named
  **`concept_id`** (`store.py:1239`). Pass positionally or use the right name.
- ~~`WikiRelatedTool._execute` being a supported entry point~~ — it is private
  (`wiki/tools.py:250`) and it wraps the result in a `ToolResult`. Spec §2 says
  "delegates to" `WikiRelatedTool`, but the **simpler and more honest** delegation
  is to call `store.neighbors(page_id)` directly — same call the tool makes
  (`tools.py:255`), no `ToolResult` unwrapping, no private-API dependency. Prefer
  that; note the deviation in your Completion Note.
- ~~a `mode` value named `"fts"` / `"bm25"` / `"graph"`~~ — the accepted values are
  `lexical` / `vector` / `combined` (+ the legacy aliases).
- ~~`search_code` being allowed to raise~~ — spec §2/§7: warn and degrade.

---

## Implementation Notes

### Pattern to Follow — lazy plane with a cached reason

```python
    async def _plane(self) -> tuple[Optional[Any], str]:
        """Return the cached (store, reason) pair, opening it on first use.

        An injected ``wiki_store`` short-circuits resolution entirely, which is
        what keeps the unit tests hermetic.
        """
        if self._wiki_store is not None:
            return self._wiki_store, ""
        if self._plane_cached is None:
            self._plane_cached = await open_plane(self._repo_root)
        return self._plane_cached
```

Initialise `self._plane_cached: Optional[tuple] = None` in `__init__` — note this
means TASK-2638's constructor gains one private attribute. That is fine; it is not
a signature change.

### Pattern to Follow — degrade honestly

```python
    async def _degrade(self, query: str, reason: str) -> RepoSearchResult:
        """Serve a grep result in place of a graph result, and SAY SO.

        Spec §7 forbids silent degradation: the marker and the reason travel in
        the payload the model reads, and a warning is logged for the operator.
        """
        self.logger.warning(
            "search_code degrading to grep_files: %s (query=%r)", reason, query,
        )
        fallback = await self.grep_files(query)
        if isinstance(fallback, RepoSearchResult):
            fallback.degraded = True
            fallback.degraded_reason = reason
            return fallback
        return RepoSearchResult(
            query=query, hits=[], degraded=True,
            degraded_reason=f"{reason}; grep fallback also failed",
        )
```

### Pattern to Follow — the search itself

```python
    @tool_schema(SearchCodeInput)
    async def search_code(
        self,
        query: str,
        top_k: int = 12,
        mode: Optional[Literal["lexical", "vector", "combined"]] = None,
    ) -> RepoSearchResult:
        """Search the codebase's structural index for relevant files and modules.

        PREFER THIS over `grep_files` for any question about where something
        lives or how modules relate: it returns ranked, deduplicated results
        with summaries and skips build artifacts, where grep returns raw
        unranked line matches. Use `grep_files` only for exact strings,
        regexes, or config values this index does not cover.

        Args:
            query: What you are looking for — name the symbol, module or
                subsystem, not your theory about where it might be.
            top_k: Maximum results to return.
            mode: "lexical" (default) matches names and text — best for
                symbols and modules. "combined" also considers semantic
                similarity where available. "vector" is semantic only. When
                semantic search is not configured, these fall back to lexical
                and the result is marked degraded.

        Returns:
            RepoSearchResult. Check `degraded`: when True, the structural index
            was unavailable and these are weaker grep-based results.
        """
        store, reason = await self._plane()
        if store is None:
            return await self._degrade(query, reason or "no wiki plane")

        effective = mode or self._default_search_mode
        note = ""
        if effective == "vector":
            # No embedder ships (spec §8 Q4), so the vector leg is skipped
            # (search.py:202) and a pure-vector query would return nothing.
            effective, note = "lexical", "semantic search not configured"

        try:
            search = WikiCombinedSearch(
                pageindex_toolkit=None, graphindex_toolkit=None, store=store,
            )
            results = await search.search(
                query,
                mode=effective,
                top_k=min(top_k, self._max_search_hits),
                tree_name=self._wiki_name,
            )
            packed = pack_results(         # SYNC — no await
                results, budget_tokens=self._search_budget_tokens,
            )
        except Exception as exc:  # noqa: BLE001
            return await self._degrade(query, f"plane query failed: {exc}")

        hits = [
            RepoSearchHit(
                page_id=r.node_id,          # NOT r.page_id
                path=r.title,               # NOT r.path
                summary=r.snippet,          # NOT r.summary
                outline=[],                 # not available from a search
                score=r.score,
                approx_tokens=r.token_count,  # NOT r.approx_tokens
            )
            for r in results[: packed.results_packed or len(results)]
        ]
        return RepoSearchResult(
            query=query, hits=hits,
            degraded=bool(note), degraded_reason=note,
            total_tokens=packed.tokens_used,
        )
```

### Key Constraints

> **Gotcha — the `dev_loop` grep.** TASK-2642 ships a test asserting the string
> `dev_loop` appears nowhere in `parrot/tools/repo/*.py` (spec §5: "No dev-flow /
> dev-loop import anywhere"). That test greps **raw source**, so a *comment* or
> docstring citing `parrot/flows/dev_loop/wiki_search.py` as a reference will fail
> it just as an import would. Cite that reference in **this task file** and in the
> commit message, not in the shipped source. If you want a pointer in the code,
> write it without the literal token — e.g. "mirrors the best-effort plane-open
> pattern used elsewhere in the codebase (see the feature spec §7)".


- **The happy path must spawn no subprocess.** Spec §5. Test asserts it.
- `pack_results` is **sync**. Awaiting it is a `TypeError`.
- `total_tokens <= search_budget_tokens` — an acceptance criterion. Take it from
  `packed.tokens_used`, do not compute your own estimate.
- Every failure degrades; `search_code` never raises and never returns `None`.
- Helpers underscore-prefixed (`_plane`, `_degrade`) so `_generate_tools()`
  (`toolkit.py:537`) does not expose them as tools.
- No embedder. No plane build. No `dev_flow`/`dev_loop` import anywhere in the
  package (spec §5 acceptance criterion).
- `self.logger.warning` on every degradation — the operator signal matters as much
  as the model-facing marker.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py:91-135` —
  `build_research_context`: the best-effort search+pack pattern spec §7 tells you
  to mirror. Note it uses `mode="combined"`, `top_k=25`, and
  `tree_name=self._wiki_name`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/search.py:150-232` — read
  `_search_store` in full; it is what your `mode` argument actually drives.
- `packages/ai-parrot/src/parrot/knowledge/wiki/models.py:258` — the real
  `WikiSearchResult` fields.

---

## Acceptance Criteria

- [ ] `search_code` and `related_code` appear in `get_tools()`; the toolkit still
      exposes no write-shaped tool
- [ ] `search_code` queries the plane: `WikiCombinedSearch.search` is called and
      **no grep subprocess is spawned** on the happy path
- [ ] Results are mapped correctly: `page_id`←`node_id`, `path`←`title`,
      `summary`←`snippet`, `approx_tokens`←`token_count`, `outline`==`[]`
- [ ] `total_tokens <= search_budget_tokens` for every result
- [ ] `top_k` is clamped to `max_search_hits`
- [ ] **`mode` is exposed in the tool schema** as `lexical|vector|combined` (§8 Q2)
- [ ] `mode=None` uses `default_search_mode`; an explicit `mode` is forwarded to
      `WikiCombinedSearch.search`
- [ ] `mode="vector"` with no embedder returns lexical results marked
      `degraded=True` with a reason — it does **not** return empty and does **not**
      raise
- [ ] `mode="combined"` with no embedder works (vector leg skipped, lexical
      weighted 1.0)
- [ ] **Degrades to grep when the plane is missing**: `degraded=True`,
      `degraded_reason` non-empty, hits still returned, and a warning logged
- [ ] **Degrades when the plane raises**: a store whose `search_fts` raises still
      yields a degraded result, not an exception
- [ ] `related_code` returns neighbours for a page id and degrades without a plane
- [ ] A direct `grep_files` call still reports `degraded=False` (TASK-2639's
      contract is not broken)
- [ ] No `dev_flow` / `dev_loop` import:
      `grep -rn "dev_flow\|dev_loop" packages/ai-parrot/src/parrot/tools/repo/`
      returns nothing
- [ ] Tests pass: `pytest packages/ai-parrot/tests/tools/repo/ -v`
- [ ] Clean: `ruff check` + `mypy` on the package

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/repo/conftest.py   (ADD)
import pytest


class _StubStore:
    """Answers search_fts with fixed rows; neighbors with fixed edges."""

    def __init__(self, rows=None, neighbors=None, raises=False):
        self._rows = rows if rows is not None else [
            {"concept_id": "file:pkg/sub/mod.py", "title": "pkg/sub/mod.py",
             "content": "def alpha(): ...", "score": 0.9, "token_count": 120},
        ]
        self._neighbors = neighbors or [
            {"concept_id": "dir:pkg", "title": "pkg", "rel": "contains"},
        ]
        self._raises = raises
        self.fts_calls = 0

    async def search_fts(self, query, category=None, limit=10):
        self.fts_calls += 1
        if self._raises:
            raise RuntimeError("plane is broken")
        return list(self._rows)

    async def search_vector(self, embedding, limit=10):
        return []

    async def neighbors(self, concept_id, rel=None, direction="both"):
        if self._raises:
            raise RuntimeError("plane is broken")
        return list(self._neighbors)


@pytest.fixture
def stub_wiki_store():
    return _StubStore()


@pytest.fixture
def broken_wiki_store():
    return _StubStore(raises=True)
```

```python
# packages/ai-parrot/tests/tools/repo/test_search_code.py
import pytest
from pathlib import Path

from parrot.tools.repo import ReadOnlyRepoToolkit
from parrot.tools.repo.models import RepoSearchResult


@pytest.fixture
def graph_toolkit(temp_repo: Path, stub_wiki_store) -> ReadOnlyRepoToolkit:
    return ReadOnlyRepoToolkit(repo_root=temp_repo, wiki_store=stub_wiki_store)


class TestSearchCodeHappyPath:
    async def test_queries_plane_not_grep(self, graph_toolkit, stub_wiki_store,
                                          monkeypatch):
        """Spec §5: no grep subprocess on the happy path."""
        async def _boom(*a, **k):
            raise AssertionError("grep subprocess spawned on the happy path")
        monkeypatch.setattr(graph_toolkit, "_run_argv", _boom)

        out = await graph_toolkit.search_code("alpha")
        assert isinstance(out, RepoSearchResult)
        assert out.degraded is False
        assert stub_wiki_store.fts_calls == 1
        assert out.hits

    async def test_field_mapping(self, graph_toolkit):
        out = await graph_toolkit.search_code("alpha")
        hit = out.hits[0]
        assert hit.page_id == "file:pkg/sub/mod.py"   # from node_id
        assert hit.path == "pkg/sub/mod.py"           # from title
        assert hit.summary                             # from snippet
        assert hit.outline == []                       # not available
        assert hit.approx_tokens >= 0                  # from token_count

    async def test_respects_token_budget(self, temp_repo, stub_wiki_store):
        tk = ReadOnlyRepoToolkit(
            repo_root=temp_repo, wiki_store=stub_wiki_store,
            search_budget_tokens=50,
        )
        out = await tk.search_code("alpha")
        assert out.total_tokens <= 50

    async def test_top_k_clamped(self, temp_repo, stub_wiki_store):
        tk = ReadOnlyRepoToolkit(
            repo_root=temp_repo, wiki_store=stub_wiki_store, max_search_hits=2,
        )
        out = await tk.search_code("alpha", top_k=100)
        assert len(out.hits) <= 2


class TestSearchMode:
    def test_mode_in_tool_schema(self, graph_toolkit):
        """§8 Q2: the model can see and set `mode`."""
        tool = next(t for t in graph_toolkit.get_tools()
                    if t.name == "search_code")
        schema = str(getattr(tool, "args_schema", "")) + str(tool.__dict__)
        assert "mode" in schema

    async def test_mode_forwarded(self, temp_repo, stub_wiki_store, monkeypatch):
        seen = {}
        from parrot.knowledge.wiki import search as search_mod

        class _Spy(search_mod.WikiCombinedSearch):
            async def search(self, query, mode="combined", **kw):
                seen["mode"] = mode
                return []
        monkeypatch.setattr(search_mod, "WikiCombinedSearch", _Spy)
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, wiki_store=stub_wiki_store)
        await tk.search_code("alpha", mode="combined")
        assert seen["mode"] == "combined"

    async def test_mode_defaults_to_constructor(self, temp_repo, stub_wiki_store):
        tk = ReadOnlyRepoToolkit(
            repo_root=temp_repo, wiki_store=stub_wiki_store,
            default_search_mode="combined",
        )
        out = await tk.search_code("alpha")
        assert isinstance(out, RepoSearchResult)

    async def test_vector_degrades_not_empty(self, graph_toolkit):
        """No embedder ships — vector must degrade to lexical, not return []."""
        out = await graph_toolkit.search_code("alpha", mode="vector")
        assert out.degraded is True
        assert out.degraded_reason
        assert out.hits, "vector mode returned nothing instead of degrading"


class TestDegradation:
    async def test_degrades_when_plane_missing(self, temp_repo, caplog):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo)   # no store, no plane
        out = await tk.search_code("def alpha")
        assert out.degraded is True
        assert out.degraded_reason
        assert any("degrading" in r.message.lower() or "degrad" in r.message.lower()
                   for r in caplog.records)

    async def test_degrades_when_plane_raises(self, temp_repo, broken_wiki_store):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo,
                                 wiki_store=broken_wiki_store)
        out = await tk.search_code("def alpha")
        assert out.degraded is True
        assert "failed" in out.degraded_reason.lower() or out.degraded_reason

    async def test_direct_grep_is_not_degraded(self, graph_toolkit):
        """TASK-2639's contract must survive: grep_files alone is not degraded."""
        out = await graph_toolkit.grep_files("def alpha")
        assert out.degraded is False


class TestRelatedCode:
    async def test_returns_neighbors(self, graph_toolkit):
        out = await graph_toolkit.related_code("file:pkg/sub/mod.py")
        assert isinstance(out, RepoSearchResult)
        assert out.hits

    async def test_degrades_without_plane(self, temp_repo):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo)
        out = await tk.related_code("file:whatever")
        assert out.degraded is True


class TestNoDevFlowImport:
    def test_package_does_not_import_dev_flow(self):
        import pathlib
        pkg = pathlib.Path("packages/ai-parrot/src/parrot/tools/repo")
        for f in pkg.rglob("*.py"):
            src = f.read_text()
            assert "dev_flow" not in src, f
            assert "dev_loop" not in src, f
```

---

## Agent Instructions

1. **Read the spec** — §1 (the measured grep-vs-graph comparison), §2, §3 Module 4,
   §5, §7, §8 Q2 and Q4.
2. **Check dependencies** — TASK-2639 and TASK-2641 must both be in
   `sdd/tasks/completed/`. You need `grep_files`, `_run_argv`, and `open_plane`.
3. **Verify the Codebase Contract.** Do not skip this: read
   `wiki/models.py:258` for the real `WikiSearchResult` fields and
   `wiki/search.py:150-232` for what `mode` actually does. The field-mapping table
   above exists because the obvious guesses are all wrong.
4. Update the index → `"in-progress"`.
5. **Implement** per scope. No embedder, no plane build, no dev_loop import.
6. **Verify** all acceptance criteria — especially "no grep on the happy path" and
   the `mode="vector"` degradation.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note.** If you delegated `related_code` to
   `store.neighbors` rather than `WikiRelatedTool` (recommended above), record that
   as a deliberate deviation from spec §2's wording.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
