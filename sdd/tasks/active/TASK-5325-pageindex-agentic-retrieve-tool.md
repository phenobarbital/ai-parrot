# TASK-5325: `PageIndexToolkit.agentic_retrieve` tool, kwargs, clone, exports

**Feature**: FEAT-843 — PageIndex Agentic Retrieval and Citations
**Spec**: `sdd/specs/pageindex-agentic-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5321, TASK-5324
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview, "Snapshot binding", "Dedicated client", "Deadline"; §3 Module 4; AC-9,
AC-12, AC-16, AC-19. Wires the retriever (TASK-5324) onto the toolkit using the snapshot
helpers (TASK-5321): one deadline at entry, clone lock, pin (deepcopy) before stage 1,
snapshot-bound search, outline of the top candidate, `AgenticRetriever.run`.

---

## Scope

- Add `"pageindex_agentic_retrieve"` to `llm_dependent_tools`.
- Constructor kwargs `agentic_client`, `agentic_budget_chars=40000`, `agentic_max_reads=12`,
  `agentic_max_tool_calls=20`, `agentic_timeout_s=120.0`; store them; `self._agentic_clone = None`;
  `self._agentic_lock = asyncio.Lock()`.
- `_agentic_client()` — `agentic_client` if given, else cached `clone_for_tools(self._adapter.client)`;
  `ValueError` when neither and no adapter.
- `async agentic_retrieve(tree_name, query, top_k=5, draft_answer=True, budget_chars=None, max_reads=None, timeout_s=None) -> dict`:
  validate positive finite timeout and positive ints (`ValueError`) BEFORE any work; resolve client
  (ValueError without adapter — AC-12); `deadline = loop.time() + timeout_s`; acquire
  `_agentic_lock` within the remaining time (timeout → bundle `stopped="timeout"`, `generation=None`,
  empty candidates); `tree = copy.deepcopy(self._load_tree(tree_name))`; stage 1 =
  `self._agentic_search(tree_name, tree).search(query=query, top_k=top_k, use_bm25=True,
  use_llm_walk=self._adapter is not None, use_vec=self._use_vec_rank)` under the deadline; outline =
  `self._outline_on(tree_name, tree, node_id=<top candidate node_id or None>)`; run the retriever with
  `read_tools=self._agentic_read_tools(tree_name, tree)` and
  `load_revision=lambda d, r: self._segment_store.load_revision(tree_name, d, r)`; return `bundle.model_dump()`.
- Export `Citation`, `EvidenceBundle`, `ReadLedger`, `validate_citations` from `knowledge/pageindex/__init__.py`.
- End-to-end tests appended to `test_agentic_retrieval.py`.

**NOT in scope**: template `exclude:` (TASK-5326); docs (TASK-5327); any change under `clients/`, `bots/`, `mcp/` (AC-14).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | Tool, kwargs, client clone, `llm_dependent_tools` |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py` | MODIFY | Exports |
| `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py` | MODIFY | Toolkit-level and e2e tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# toolkit.py already has: asyncio, copy (:21-22), AbstractClient (:34), HybridPageIndexSearch (:40)
from .agentic import AgenticRetriever, EvidenceBundle, clone_for_tools      # TASK-5323/5324
# __init__.py:
from .citations import Citation, validate_citations                          # TASK-5322
from .read_ledger import ReadLedger                                          # TASK-5320
from .agentic import EvidenceBundle                                          # TASK-5323
```
Import `agentic` in `toolkit.py` at module top only if it creates no cycle (`agentic.py` must not import `toolkit`); verify with `python -c "import parrot.knowledge.pageindex"`.

### Existing Signatures to Use
```python
# toolkit.py (HEAD 7d73c97ea9; TASK-5321 shifts lines — re-grep)
llm_dependent_tools: frozenset[str] = frozenset({... "pageindex_search_documents_scoped",})   # :135-143
def __init__(self, adapter=None, storage_dir=None, ..., read_max_chars: int = 12000, *, llm_client=None, max_result_chars=None, **kwargs)  # :145-170
self._adapter: Optional[PageIndexLLMAdapter]        # :177 (.client / .model)
self._segment_store = SegmentStore(storage_dir)     # :192; load_revision(tree_name, doc_id, revision) -> Optional[DocumentRevision] (segment_store.py:64)
self._max_result_chars = max_result_chars           # :199
def _load_tree(self, tree_name) -> dict             # :405
# from TASK-5321:
def _agentic_search(self, tree_name, tree) -> HybridPageIndexSearch
def _agentic_read_tools(self, tree_name, tree) -> list[ToolkitTool]
async def _outline_on(self, tree_name, tree, node_id=None, max_depth=3, max_chars=6000) -> dict
# from TASK-5324:
AgenticRetriever(*, client, model, read_tools, load_revision).run(*, tree_name, query, candidates, outline,
    generation, budget_chars, max_reads, max_tool_calls, deadline, draft_answer) -> EvidenceBundle
# generation_of(tree) (generation.py) -> object with .id, or None   — used at toolkit._read
```

### Does NOT Exist
- ~~`PageIndexToolkit.agentic_retrieve`, `_agentic_client`, `agentic_*` kwargs~~ — you add them.
- ~~calling `register_tools` on `self._adapter.client`~~ — forbidden; only the clone.
- ~~using `self._search_for` / `self.search` for stage 1~~ — must be the snapshot engine (AC-16).
- ~~`AbstractToolkit.list_tool_names()` returning names without the prefix~~ — check its actual output in `tools/toolkit.py` before asserting.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._load_tree",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py#SegmentStore.load_revision"
  ]
}
```

---

## Implementation Notes

- The lock serializes concurrent calls on one clone (spec Dedicated client); hold it for the whole run.
- Default model for the retriever: `self._model`.
- Timeout bundle before pinning: `EvidenceBundle(tree_name=..., query=..., stopped="timeout").model_dump()`.
- The docstring is the LLM-facing description — keep the spec's text.

---

## Implementation Blueprint

### Steps (in order)
1. `llm_dependent_tools` entry.
2. Constructor kwargs + attributes.
3. `_agentic_client` and `agentic_retrieve` before `index_segments`.
4. `__init__.py` exports.
5. Tests; run, plus `test_toolkit.py` and `test_read_tools.py` regressions.

### `toolkit.py` (MODIFY) — llm_dependent_tools
```python
# AFTER `            "pageindex_search_documents_scoped",` (verified: toolkit.py:141) — occurrences: 1
            "pageindex_agentic_retrieve",
```

### `toolkit.py` (MODIFY) — constructor
```python
# AFTER `        read_max_chars: int = 12000,` (verified: toolkit.py:164) — occurrences: 1
        agentic_client: Optional[AbstractClient] = None,
        agentic_budget_chars: int = 40000,
        agentic_max_reads: int = 12,
        agentic_max_tool_calls: int = 20,
        agentic_timeout_s: float = 120.0,

# AFTER `        self._max_result_chars = max_result_chars` (verified: toolkit.py:199) — occurrences: 1
        self._agentic_client_override = agentic_client
        self._agentic_budget_chars = agentic_budget_chars
        self._agentic_max_reads = agentic_max_reads
        self._agentic_max_tool_calls = agentic_max_tool_calls
        self._agentic_timeout_s = agentic_timeout_s
        self._agentic_clone: Optional[AbstractClient] = None
        self._agentic_lock = asyncio.Lock()
```
**Why**: the kwargs go BEFORE the bare `*` (positional-or-keyword, like their neighbours) — the
spec skeleton places them after `read_max_chars`. Validate them in `agentic_retrieve`, not here,
so existing constructions never raise.

### `toolkit.py` (MODIFY) — tool
```python
# BEFORE `    async def index_segments(self, tree_name: str, node_id: Optional[str] = None) -> dict[str, Any]:`
# occurrences: 1 (re-verify after TASK-5321)
    def _agentic_client(self) -> AbstractClient:
        """``agentic_client`` if given, else a cached ``clone_for_tools(self._adapter.client)``; ValueError with no adapter."""
        if self._agentic_client_override is not None:
            return self._agentic_client_override
        if self._adapter is None:
            raise ValueError("agentic retrieval requires an LLM; configure a model for this toolkit")
        if self._agentic_clone is None:
            self._agentic_clone = clone_for_tools(self._adapter.client)
        return self._agentic_clone

    async def agentic_retrieve(
        self, tree_name: str, query: str, top_k: int = 5, draft_answer: bool = True,
        budget_chars: Optional[int] = None, max_reads: Optional[int] = None, timeout_s: Optional[float] = None,
    ) -> dict[str, Any]:
        """Stage-1 search, then a bounded reading loop that returns cited evidence.

        Returns an evidence bundle: candidates, the exact ranges read, validated citations
        (``[Report.pdf, p. 12 ¶3]``), rejected ones with reasons, and optionally a drafted
        answer. ``grounded`` is false when no citation survived validation. Requires an LLM."""
        # FILL IN: resolve + validate budgets/timeout (positive, finite) -> ValueError
        client = self._agentic_client()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        # FILL IN: lock acquire under remaining time (timeout bundle); inside the lock:
        #          pin deepcopy; stage-1 via self._agentic_search(...).search(...) under remaining time;
        #          outline via self._outline_on; generation via generation_of(tree);
        #          AgenticRetriever(client=client, model=self._model, read_tools=self._agentic_read_tools(tree_name, tree),
        #                           load_revision=lambda d, r: self._segment_store.load_revision(tree_name, d, r)).run(...)
        #          timeouts before run -> bundle stopped="timeout" with what is known — AC-16, AC-19
        raise NotImplementedError
```

### `__init__.py` (MODIFY)
```python
# AFTER `from .segment_store import SegmentStore` (verified: __init__.py:26) — occurrences: 1
from .read_ledger import ReadLedger
from .citations import Citation, validate_citations
from .agentic import EvidenceBundle
# and append "ReadLedger", "Citation", "validate_citations", "EvidenceBundle" to __all__ (:28)
```

### `test_agentic_retrieval.py` (MODIFY — append)
```python
# FILL IN: fixtures copied from test_read_tools.py:20-75 (_adapter, _stub_tiktoken autouse, toolkit, _fake_build, paged_toolkit)
#          with a segment longer than the test budget
# FILL IN: test_end_to_end_cited_evidence — scripted client reads p.1 then continues via cursor, cites both;
#          reads == ledger, kept/rejected, rendered labels, grounded True, tool_calls, usage — AC-9
# FILL IN: test_citations_survive_reimport_within_grace — re-import between prefix read and continuation — AC-16
# FILL IN: test_agentic_retrieve_without_adapter_raises — AC-12
# FILL IN: test_tool_listed_and_llm_dependent — name in PageIndexToolkit.llm_dependent_tools and tool names — AC-12
# FILL IN: test_adapter_client_registry_untouched — AC-8/AC-14 (adapter.client.tool_manager has no pageindex tools)
# FILL IN: test_timeout_during_lock_wait and during stage-1 search — AC-19
```

### FILL IN checklist
- [ ] parameter validation
- [ ] lock/pin/search/outline/run body
- [ ] tests

---

## Acceptance Criteria

- [ ] AC-9, AC-12, AC-14, AC-16 (end-to-end), AC-19 (lock wait / search phases).

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_read_tools.py -q`

---

## Test Specification

Spec §4 integration rows `test_end_to_end_cited_evidence`, `test_citations_survive_reimport_within_grace`.

---

## Agent Instructions

1. Re-grep every anchor (TASK-5321 edited `toolkit.py`).
2. `ruff check --fix`; run validation with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit: `feat(pageindex-agentic-retrieval): TASK-5325 — agentic_retrieve tool`.

---

## Completion Note

*(Agent fills this in when done)*
