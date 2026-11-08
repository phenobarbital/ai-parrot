# TASK-5314: PageIndexToolkit constructor without an LLM + deterministic search/retrieve

**Feature**: FEAT-842 — PageIndex Local MCP Toolkit
**Spec**: `sdd/specs/pageindex-local-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 1** (constructor without an LLM) and the toolkit half of
**Module 2** (deterministic degradation). Today `PageIndexToolkit.__init__` requires a
`PageIndexLLMAdapter`; the local MCP factory (`mcp/toolkit_server.py:338-342`) builds the
toolkit as `toolkit_cls(**kwargs)` and passes the configured model as
`kwargs["llm_client"]`, never an adapter, so a `pageindex:` section fails to instantiate.
The class also declares no `llm_dependent_tools`, so the factory cannot hide the tools
that need a model, and `search`/`retrieve` would crash in `_llm_rank` with no adapter.

---

## Scope

- Make `adapter` optional (`Optional[PageIndexLLMAdapter] = None`) and keep `storage_dir`
  the second positional parameter; raise `ValueError` when `storage_dir` is `None`.
- Add the keyword `llm_client: Optional[AbstractClient] = None`. Resolution rule:
  `adapter` given → used as is; else `llm_client` given →
  `PageIndexLLMAdapter(client=llm_client, model=model)`; else no adapter. Both given →
  `ValueError("pass either adapter or llm_client, not both")`.
- `self._model = model or (self._adapter.model if self._adapter is not None else None)`;
  build `self._light_adapter` only when `self._adapter is not None and lightweight_model`.
- Add the class attribute `llm_dependent_tools` with the five prefixed names (AC-3).
- Add the `has_llm` property.
- In `search`: compute `llm_walk = use_llm_walk and self._adapter is not None`; raise
  `ValueError("LLM walk requested but no LLM is configured for this toolkit")` when the
  walk was asked for, there is no adapter and no other signal is on; pass
  `use_llm_walk=llm_walk` to the engine.
- In `retrieve`: replace `use_llm_walk=True,` with `use_llm_walk=self._adapter is not None,`.
- Create `tests/knowledge/pageindex/test_toolkit_no_llm.py` covering AC-1..AC-4.

**NOT in scope**: `max_result_chars` / `_bound_text` (TASK-5316); `HybridPageIndexSearch`
changes (TASK-5315); the template (TASK-5317); any change in `mcp/` (AC-12 forbids it);
making `search_documents_scoped` BM25-capable (spec §7: stays LLM-only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | optional adapter, `llm_client`, `llm_dependent_tools`, `has_llm`, search/retrieve guards |
| `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py` | CREATE | constructor + no-LLM behaviour tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `1db2685b95` (2026-11-07). Paths relative to
> `packages/ai-parrot/src/parrot/` unless they start with `packages/`.

### Verified Imports
```python
from parrot.clients.base import AbstractClient                         # clients/base.py; imported by knowledge/pageindex/llm_adapter.py:9 — NOT yet imported by toolkit.py
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit        # knowledge/pageindex/toolkit.py:63
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter # llm_adapter.py:43; toolkit.py already imports it at :38 (`from .llm_adapter import PageIndexLLMAdapter`)
# toolkit.py already has: `from typing import Any, AsyncIterator, Awaitable, Callable, Optional, TypeVar` (:29)
# and `from __future__ import annotations` (:19)
```

### Existing Signatures to Use
```python
# knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):                  # :63
    name = "pageindex"                                    # :98
    tool_prefix = "pageindex"                             # :99
    def __init__(self, adapter: PageIndexLLMAdapter, storage_dir: str | Path, reranker=None,
                 lightweight_model=None, model=None, default_bm25_k=20, folder_concurrency=4,
                 content_cache_size=256, embedding_model=None, embedding_dimension=256,
                 embedding_backend=None, use_vec_rank=False, use_embedding_walk=False,
                 generation_grace_s=3600, lock_timeout_s=30.0, **kwargs)   # :101-119 (lock_timeout_s at :117)
        super().__init__(**kwargs)                        # :120
        self._adapter = adapter                           # :121
        self._storage_dir = Path(storage_dir)             # :122
        self._light_adapter = (PageIndexLLMAdapter(client=adapter.client, model=lightweight_model) if lightweight_model else None)  # :125-127
        self._store = JSONTreeStore(storage_dir)          # :128
        self._model = model or adapter.model              # :131
    def _ingester(self) -> TwoStepIngester                # :296
    def _search_for(self, tree_name) -> HybridPageIndexSearch   # :321 (passes adapter=self._adapter)
    async def search(self, tree_name, query, top_k=10, use_bm25=True, use_llm_walk=True, rerank=False,
                     categories=None, metadata_filter=None) -> list[dict]   # :655; engine = ... at :679; use_llm_walk=use_llm_walk at :690
    async def retrieve(self, tree_name, query, top_k=5) -> str             # :722; use_llm_walk=True at :739
    async def insert_markdown(...)                        # :922; md_to_tree(..., adapter=self._adapter, ...) at :945
    # tag_node helper already has `if self._adapter is not None:` (:427)

# tools/toolkit.py
class AbstractToolkit:
    llm_dependent_tools: frozenset = frozenset()          # :313 (default; factory reads it as a class attribute)

# knowledge/pageindex/llm_adapter.py
class PageIndexLLMAdapter:
    def __init__(self, client: AbstractClient, model: Optional[str] = "gemini-3.1-flash-lite-preview", ...)  # :49; self.client / self.model at :56-57

# knowledge/pageindex/hybrid_search.py
#   HybridPageIndexSearch.search raises ValueError when no signal is enabled  # :348
#   HybridPageIndexSearch.__init__ only stores adapter (self._adapter = adapter, :90) — no dereference at construction
```

Tool names (`tool_prefix` applied): `pageindex_insert_content`, `pageindex_import_file`,
`pageindex_import_folder`, `pageindex_import_pdf`, `pageindex_search_documents_scoped`
are the five LLM-dependent ones; verified in `tests/knowledge/pageindex/test_toolkit.py:77-79`.

### Does NOT Exist
- ~~`PageIndexToolkit(llm_client=...)`~~, ~~`PageIndexToolkit.has_llm`~~, ~~`PageIndexToolkit.llm_dependent_tools`~~ (own) — created by this task
- ~~`AbstractToolkit.opt_in_tools`~~ — no such attribute
- ~~`parrot.knowledge.pageindex.toolkit.AbstractClient`~~ — not imported there yet; add the import
- ~~a default model name in the toolkit~~ — spec Non-Goal: never add one

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.__init__",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.search",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.retrieve",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py#PageIndexLLMAdapter",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keep `storage_dir` positional-second: `PageIndexToolkit(adapter, tmp_path)` is used by the
  FEAT-831 tests and by Bookstore.
- Do not import anything that prints at import time (navconfig banner) — the stdio server
  calls tools outside the factory's stdout redirect. `parrot.clients.base` is already
  imported by `llm_adapter.py`, so the new import adds no new side effect.
- FEAT-840 (`pageindex-segment-store`) also edits `toolkit.py` (read tools after `get_tree`);
  whichever feature merges second rebases — do not touch `get_tree`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the `AbstractClient` import — *why*: the new `llm_client` annotation needs it.
2. Add `llm_dependent_tools` under `tool_prefix` — *why*: the factory reads it as a class attribute and matches prefixed `t.name`.
3. Change the constructor signature and the resolution block — *why*: the factory passes `llm_client`, never `adapter`.
4. Add `has_llm` above `_ingester` — *why*: a single public way to ask whether model-dependent features work.
5. Guard `search` and `retrieve` — *why*: without an adapter the engine would reach `_llm_rank` and crash.
6. Write the tests — *why*: AC-1..AC-4.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .llm_adapter import PageIndexLLMAdapter' toolkit.py)
# AFTER — insert below `from parrot.tools.toolkit import AbstractToolkit` (verified: toolkit.py:31)
from parrot.clients.base import AbstractClient

# occurrences: 1 (verified: grep -cF '    tool_prefix = "pageindex"' toolkit.py)
# AFTER — insert below `    tool_prefix = "pageindex"` (verified: toolkit.py:99)
    #: Tools the local MCP factory hides when the section has no ``llm`` (names carry the prefix).
    llm_dependent_tools: frozenset[str] = frozenset(
        {
            "pageindex_insert_content",
            "pageindex_import_file",
            "pageindex_import_folder",
            "pageindex_import_pdf",
            "pageindex_search_documents_scoped",
        }
    )

# occurrences: 1 (verified: grep -cF '        adapter: PageIndexLLMAdapter,' toolkit.py)
# REPLACE `        adapter: PageIndexLLMAdapter,` and `        storage_dir: str | Path,` (toolkit.py:103-104) with:
        adapter: Optional[PageIndexLLMAdapter] = None,
        storage_dir: Optional[str | Path] = None,

# occurrences: 1 (verified: grep -cF '        lock_timeout_s: float = 30.0,' toolkit.py)
# AFTER — insert below `        lock_timeout_s: float = 30.0,` (verified: toolkit.py:117)
        *,
        llm_client: Optional[AbstractClient] = None,
# FILL IN: add `llm_client` to the __init__ docstring Args (wrapped into
#   PageIndexLLMAdapter(client=llm_client, model=model); mutually exclusive with adapter).

# occurrences: 1 (verified: grep -cF '        self._adapter = adapter' toolkit.py)
# REPLACE `        self._adapter = adapter` (toolkit.py:121) with:
        if adapter is not None and llm_client is not None:
            raise ValueError("pass either adapter or llm_client, not both")
        if storage_dir is None:
            raise ValueError("PageIndexToolkit requires storage_dir")
        if adapter is None and llm_client is not None:
            adapter = PageIndexLLMAdapter(client=llm_client, model=model)
        self._adapter: Optional[PageIndexLLMAdapter] = adapter

# occurrences: 1 (verified: grep -cF 'PageIndexLLMAdapter(client=adapter.client, model=lightweight_model) if lightweight_model else None' toolkit.py)
# REPLACE that line (toolkit.py:126) with:
            PageIndexLLMAdapter(client=self._adapter.client, model=lightweight_model)
            if self._adapter is not None and lightweight_model
            else None

# occurrences: 1 (verified: grep -cF '        self._model = model or adapter.model' toolkit.py)
# REPLACE (toolkit.py:131) with:
        self._model = model or (self._adapter.model if self._adapter is not None else None)

# occurrences: 1 (verified: grep -cF '    def _ingester(self) -> TwoStepIngester:' toolkit.py)
# BEFORE — insert above `    def _ingester(self) -> TwoStepIngester:` (verified: toolkit.py:296)
    @property
    def has_llm(self) -> bool:
        """True when an LLM adapter is configured (LLM walk and ingest tools available)."""
        return self._adapter is not None

# occurrences: 1 (verified: grep -cF '        engine = self._search_for(tree_name)' toolkit.py)
# AFTER — insert below `        engine = self._search_for(tree_name)` (verified: toolkit.py:679)
        llm_walk = use_llm_walk and self._adapter is not None
        if use_llm_walk and not llm_walk and not (use_bm25 or self._use_vec_rank or self._use_embedding_walk):
            raise ValueError("LLM walk requested but no LLM is configured for this toolkit")

# occurrences: 1 (verified: grep -cF '            use_llm_walk=use_llm_walk,' toolkit.py)
# REPLACE (toolkit.py:690) with:
            use_llm_walk=llm_walk,

# occurrences: 1 (verified: grep -cF '            use_llm_walk=True,' toolkit.py)
# REPLACE (toolkit.py:739, inside retrieve) with:
            use_llm_walk=self._adapter is not None,
```
**Why this shape**: the `*,` keeps every existing positional call working while making
`llm_client` keyword-only (spec §2 "New Public Interfaces"). The ValueError texts are fixed
by the spec and asserted by tests. The ValueError for a missing `storage_dir` replaces the
`TypeError` Python raised when it was a required positional. `lightweight_model` keeps
working on both paths because it reads `self._adapter`, which now holds the resolved
adapter. If `self._use_embedding_walk` is assigned after the search guard's attributes are
needed, that is fine: the guard runs at call time, not in `__init__`.

### `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py` (CREATE)
```python
"""PageIndexToolkit without an LLM adapter (FEAT-842 M1/M2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from parrot.clients.base import AbstractClient
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

LLM_TOOLS = {
    "pageindex_insert_content",
    "pageindex_import_file",
    "pageindex_import_folder",
    "pageindex_import_pdf",
    "pageindex_search_documents_scoped",
}

DOC = """# Field Guide

## Alpine Plants
# FILL IN: >= 60 words of body text mentioning a distinctive word (e.g. "edelweiss")

## Coastal Birds
# FILL IN: >= 60 words of body text

## River Fish
# FILL IN: >= 60 words of body text
"""


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch):
    # Copied from test_toolkit.py:52-62 — tiktoken may download encodings on first use.
    def _approx(text: str, model: str = "gpt-4o") -> int:
        return max(1, len(text or ""))

    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", _approx)
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", _approx)


def _client() -> MagicMock:
    client = MagicMock(spec=AbstractClient)
    client.default_model = "test-model"
    return client


def test_constructs_without_adapter(tmp_path: Path) -> None:
    """AC-1."""
    # FILL IN: PageIndexToolkit(storage_dir=tmp_path).has_llm is False; PageIndexToolkit(storage_dir=None) raises ValueError


def test_positional_and_keyword_adapter_unchanged(tmp_path: Path) -> None:
    """AC-1: PageIndexToolkit(a, d) and PageIndexToolkit(adapter=a, storage_dir=d)."""
    # FILL IN: build a PageIndexLLMAdapter(client=_client(), model="m"); both forms keep it; has_llm True


def test_llm_client_is_wrapped(tmp_path: Path) -> None:
    """AC-2."""
    # FILL IN: tk._adapter.client is c and tk._adapter.model == "m"; with lightweight_model="light" the light adapter shares c


def test_adapter_and_llm_client_together_raise(tmp_path: Path) -> None:
    """AC-2."""
    # FILL IN: pytest.raises(ValueError, match="either adapter or llm_client")


def test_llm_dependent_tools_names(tmp_path: Path) -> None:
    """AC-3."""
    # FILL IN: PageIndexToolkit.llm_dependent_tools == LLM_TOOLS and <= set(tk.list_tool_names())


async def test_search_and_retrieve_without_adapter(tmp_path: Path) -> None:
    """AC-4: BM25 only, retrieve returns text, insert_markdown assigns SECTION types."""
    pytest.importorskip("bm25s")
    # FILL IN: create_tree, insert_markdown(DOC); search(..., use_llm_walk=True) -> every result source == "bm25"
    #   and the distinctive word's section ranks first; retrieve(...) returns non-empty text;
    #   every node in (await tk.get_tree(name))["structure"] (walk children) has node["type"] == "Section"


async def test_llm_walk_only_without_adapter_raises(tmp_path: Path) -> None:
    """AC-4."""
    # FILL IN: search(..., use_bm25=False, use_llm_walk=True) raises ValueError("LLM walk requested ...")
```
**Why**: one test per AC clause keeps failures readable; the tiktoken stub is copied, not
imported, because importing a test module drags its `test_*` names into this module's
collection. `MagicMock(spec=AbstractClient)` is enough: no LLM call happens in these paths.

### FILL IN checklist
- [ ] `toolkit.py::__init__` docstring entry for `llm_client` — bounded by spec §3 M1 docstring text
- [ ] `test_toolkit_no_llm.py` test bodies — bounded by AC-1..AC-4
- [ ] SECTION assertion: the toolkit's typing helper writes `node["type"] = ConceptType.SECTION.value` (toolkit.py:433/439; `from parrot.knowledge.pageindex.okf.ontology import ConceptType`, imported lazily at toolkit.py:407; value `"Section"`, okf/ontology.py:43) — assert it on the nodes of `get_tree(...)["structure"]` — bounded by AC-4

---

## Acceptance Criteria

- [ ] AC-1 `PageIndexToolkit(storage_dir=d)` constructs; `has_llm is False`; `PageIndexToolkit(adapter=a, storage_dir=d)` and `PageIndexToolkit(a, d)` behave as before.
- [ ] AC-2 `PageIndexToolkit(storage_dir=d, llm_client=c, model="m")` → adapter with `client is c`, `model == "m"`; `adapter` + `llm_client` → `ValueError`.
- [ ] AC-3 `llm_dependent_tools` equals the five names and each is in `list_tool_names()`.
- [ ] AC-4 Without an adapter: `search(use_llm_walk=True)` returns `source == "bm25"` results; `search(use_bm25=False, use_llm_walk=True)` raises `ValueError`; `retrieve` returns text; `insert_markdown` assigns `SECTION` types.
- [ ] Existing `test_toolkit.py`, `test_generation_integration.py`, `test_folder_import.py` still pass.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_generation_integration.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_folder_import.py -q`

---

## Test Specification

See the CREATE block above (`test_toolkit_no_llm.py`).

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug pageindex-local-mcp-toolkit --feature-id FEAT-842`).
2. Read the spec; verify the Codebase Contract anchors with `grep -cF`.
3. Mark `in-progress` in `sdd/tasks/index/pageindex-local-mcp-toolkit.json`, commit only the index.
4. Implement from the blueprint, completing every `# FILL IN:`.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the two files, then `parrot sdd task close TASK-5314 pageindex-local-mcp-toolkit verified`.
7. Fill in the Completion Note and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
