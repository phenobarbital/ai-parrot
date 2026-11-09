# TASK-5380: Fail fast in agentic retrieval on a client without a tool loop

**Feature**: FEAT-848 — Client tool-loop capability flag
**Spec**: `sdd/specs/client-tool-loop-capability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (G3, AC-4). Today a stage-2 `AgenticRetriever` on a client whose `ask()` runs no tool
loop wastes an LLM call and returns `stopped="no_tool_calls"`, `grounded=False` — a configuration error that
looks like a model outcome. This task adds a module-level helper `require_tool_loop(client)` in `agentic.py`
and calls it at both entry points: `AgenticRetriever.__init__` (direct constructions) and
`PageIndexToolkit._agentic_client()` (override or clone), which `agentic_retrieve` calls before candidate
search. `EvidenceBundle` and `StopReason` stay unchanged.

The helper reads the flag with `getattr(client, "supports_tool_loop", True)`, so this task does not need
TASK-5379 to land first: its test client declares `supports_tool_loop = False` itself.

---

## Scope

- Add `require_tool_loop(client: AbstractClient) -> None` to `agentic.py`, before `clone_for_tools`, and list it in `__all__`.
- Call `require_tool_loop(client)` as the first statement of `AgenticRetriever.__init__`.
- Import it in `toolkit.py` and call it in `_agentic_client()` on the resolved client (override or clone) before returning.
- Append `NoLoopClient` and three tests to `test_agentic_retrieval.py`.

**NOT in scope**:
- Declaring the flag on `AbstractClient` or providers (TASK-5379).
- A new `StopReason` value, any change to `EvidenceBundle`, `clone_for_tools`, or the retrieval loop.
- Changing the existing `"agentic retrieval requires an LLM; ..."` error for a toolkit without an adapter.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py` | MODIFY | `require_tool_loop` helper, `__all__`, first statement of `AgenticRetriever.__init__` |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | import helper; check the resolved client in `_agentic_client()` |
| `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py` | MODIFY | append `NoLoopClient` + three fail-fast tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev @ d8832d3fc8` (2026-11-09).

### Verified Imports
```python
# agentic.py already has (no new import needed):
from parrot.clients.base import AbstractClient                       # verified: agentic.py:14
# toolkit.py — the agentic import is RELATIVE (spec §6 quoted it as absolute; the file uses):
from .agentic import AgenticRetriever, EvidenceBundle, clone_for_tools   # verified: toolkit.py:38 (1 occurrence)
# test_agentic_retrieval.py already has:
from parrot.knowledge.pageindex.agentic import (AgenticRetriever, _ToolCallController, clip_read_result, clone_for_tools)  # :12-17
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter   # :18
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit          # :19
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py
__all__ = ["AgenticAnswer", "EvidenceBundle", "AgenticRetriever", "clone_for_tools", "clip_read_result",
           "SYSTEM_PROMPT", "BUDGET_MESSAGE"]                                         # :29-37 ("clone_for_tools", at :33)
StopReason = Literal["answered", "budget", "max_tool_calls", "timeout", "no_tool_calls", "parse_error"]   # :42 (unchanged)
def clone_for_tools(client: AbstractClient) -> AbstractClient:                         # :82 — copy.copy(client): keeps the class, so the flag survives cloning
class AgenticRetriever:                                                                # :158
    def __init__(self, *, client: AbstractClient, model: Optional[str],
                 read_tools: Sequence[AbstractTool],
                 load_revision: Callable[[str, str], Optional[DocumentRevision]]) -> None:   # :163-170
        self._client = client                                                          # :171 (first statement)

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit:
    def __init__(..., agentic_client: Optional[AbstractClient] = None, ...)            # :167; self._agentic_client_override :207
    def _agentic_client(self) -> AbstractClient:                                       # :1145-1153 (full body quoted in the blueprint)
    async def agentic_retrieve(self, tree_name, query, top_k=5, draft_answer=True, ...)  # :1155
        # timeout validation :1186-1189; client = self._agentic_client() :1191; stage-1 search self._agentic_search(...).search(...) :1224-1225
        # returns a dict bundle (bundle["stopped"], bundle["candidates"])

# packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py (532 lines)
class StubClient(AbstractClient): client_type = "stub"; ask() raises NotImplementedError   # :27-56
def _read_tool() -> ToolkitTool                                                        # :110
@pytest.fixture async def agentic_toolkit(tmp_path, monkeypatch) -> tuple[PageIndexToolkit, ScriptedToolLoopClient, dict]   # :418-440 (tree "t", agentic_client override)
async def test_agentic_retrieve_without_adapter_raises(tmp_path)                       # :473 (pattern: pytest.raises(ValueError, match=...))
def test_adapter_client_registry_untouched(tmp_path)                                   # :489 (pattern: adapter=PageIndexLLMAdapter(client=..., model="stub"); toolkit._agentic_client())
async def test_timeout_during_stage_one_search(agentic_toolkit, monkeypatch)           # :516 — LAST test, file ends at :532; monkeypatches toolkit._agentic_search
```

### Does NOT Exist
- ~~`AgenticRetriever.require_tool_loop`~~ — the helper is module-level, not a method.
- ~~`StopReason` value `"unsupported_client"`~~ — not added; the fail-fast path raises.
- ~~`EvidenceBundle.supported`~~ / any new bundle field — the bundle contract is unchanged.
- ~~`from parrot.knowledge.pageindex.agentic import require_tool_loop`~~ in `toolkit.py` — `toolkit.py` uses the relative `from .agentic import ...` form; extend that line.
- ~~`test_tool_listed_and_llm_dependent` is the last test~~ — spec §6 said `:481`; the file grew, the last test is now `test_timeout_during_stage_one_search` (`:516`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py#clone_for_tools",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py#AgenticRetriever",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py#AgenticRetriever.__init__",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._agentic_client",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.agentic_retrieve",
    "sym:packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py#StubClient"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Error message is fixed by spec §2: `"agentic retrieval requires a client that executes tool calls inside ask(); "
  f"{type(client).__name__} ({client_type}) declares supports_tool_loop=False"`.
- Check with `is False` (identity), defaulting to `True` through `getattr` — a duck-typed client without the attribute stays capable (today's behaviour), and a `MagicMock` client is never rejected.
- The toolkit check must run on both the override and the clone, and before candidate search (AC-4). `_agentic_client()` is already called at `:1191`, before the stage-1 search at `:1224` — do not move that call.
- In a worktree, run tests with `PYTHONPATH=packages/ai-parrot/src`.

---

## Implementation Blueprint

### Steps (in order)
1. Add `require_tool_loop` to `agentic.py` and to `__all__` — *why*: one shared helper keeps the message identical at both sites (spec §3 M2).
2. Call it first in `AgenticRetriever.__init__` — *why*: direct constructions must fail before anything is stored.
3. Extend the `toolkit.py` import and restructure `_agentic_client()` so both branches end in one check — *why*: today the override branch returns early and would skip a check placed at the end.
4. Append the tests at the end of `test_agentic_retrieval.py` — *why*: AC-4 needs the error at construction, through the toolkit on a real tree before search, and on the clone path.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py` (MODIFY — 3 edits)
```python
# Edit 1 — occurrences: 1 (verified: grep -cF '    "clone_for_tools",' agentic.py)
# AFTER — insert below `    "clone_for_tools",` (verified: agentic.py:33)
    "require_tool_loop",

# Edit 2 — occurrences: 1 (verified: grep -cF 'def clone_for_tools(client: AbstractClient) -> AbstractClient:' agentic.py)
# BEFORE — insert above `def clone_for_tools(client: AbstractClient) -> AbstractClient:` (verified: agentic.py:82), followed by two blank lines
def require_tool_loop(client: AbstractClient) -> None:
    """Raise ``ValueError`` naming the client when it declares ``supports_tool_loop = False``.

    FEAT-848: agentic retrieval needs a client whose text ``ask()`` executes tool calls. The flag is
    read with a ``True`` default, so a duck-typed client without the attribute keeps today's behaviour.

    Raises:
        ValueError: ``client`` declares that its ``ask()`` runs no tool loop.
    """
    if getattr(client, "supports_tool_loop", True) is False:
        raise ValueError(
            "agentic retrieval requires a client that executes tool calls inside ask(); "
            f"{type(client).__name__} ({getattr(client, 'client_type', '?')}) declares supports_tool_loop=False"
        )

# Edit 3 — occurrences: 1 (verified: grep -cF '        self._client = client' agentic.py)
# BEFORE — insert above `        self._client = client` (verified: agentic.py:171, first statement of __init__)
        require_tool_loop(client)
```
**Why this shape**: the helper is mechanical and complete — copy it verbatim. `getattr(client, 'client_type', '?')`
keeps duck-typed clients from raising `AttributeError` instead of the intended `ValueError`.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY — 2 edits)
```python
# Edit 1 — occurrences: 1 (verified: grep -cF 'from .agentic import AgenticRetriever, EvidenceBundle, clone_for_tools' toolkit.py)
# REPLACE the line at toolkit.py:38 with:
from .agentic import AgenticRetriever, EvidenceBundle, clone_for_tools, require_tool_loop

# Edit 2 — occurrences: 1 (verified: grep -cF 'def _agentic_client(self) -> AbstractClient:' toolkit.py)
# REPLACE the whole method body (toolkit.py:1145-1153). Current body, verbatim:
#     def _agentic_client(self) -> AbstractClient:
#         """Return the dedicated agentic client, cloning the adapter client when needed."""
#         if self._agentic_client_override is not None:
#             return self._agentic_client_override
#         if self._adapter is None:
#             raise ValueError("agentic retrieval requires an LLM; configure a model for this toolkit")
#         if self._agentic_clone is None:
#             self._agentic_clone = clone_for_tools(self._adapter.client)
#         return self._agentic_clone
# New body:
    def _agentic_client(self) -> AbstractClient:
        """Return the dedicated agentic client, cloning the adapter client when needed.

        Raises ``ValueError`` when no LLM is configured, or when the resolved client declares
        ``supports_tool_loop = False`` (FEAT-848) — before any candidate search or LLM call.
        """
        if self._agentic_client_override is not None:
            client = self._agentic_client_override
        else:
            if self._adapter is None:
                raise ValueError("agentic retrieval requires an LLM; configure a model for this toolkit")
            if self._agentic_clone is None:
                self._agentic_clone = clone_for_tools(self._adapter.client)
            client = self._agentic_clone
        require_tool_loop(client)
        return client
```
**Why**: keeps the existing "requires an LLM" error and clone caching unchanged; only adds one check on whichever
client is returned. Do not move the `self._agentic_client()` call inside `agentic_retrieve`.

### `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py` (MODIFY — append)
```python
# occurrences: 1 (verified: grep -cF 'async def test_timeout_during_stage_one_search(agentic_toolkit, monkeypatch) -> None:' test_agentic_retrieval.py)
# APPEND at the end of the file, after test_timeout_during_stage_one_search (verified: :516; file ends at :532).
# Do NOT anchor on `assert bundle["candidates"] == []` — it occurs twice (:512, :532).


class NoLoopClient(StubClient):
    """Client declaring that its text ask() runs no tool loop; counts ask() calls (FEAT-848)."""

    supports_tool_loop = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.ask_calls = 0

    async def ask(self, prompt: str, model: str | None = None, **kwargs: Any) -> Any:
        """Count the call; the fail-fast path must never reach it."""
        self.ask_calls += 1
        raise AssertionError("ask() must not be called on a client without a tool loop")


def test_agentic_retriever_rejects_no_loop_client() -> None:
    """Direct construction raises, naming the class and client_type."""
    # FILL IN: pytest.raises(ValueError, match=r"NoLoopClient \(stub\) declares supports_tool_loop=False") around
    #   AgenticRetriever(client=NoLoopClient(), model="stub", read_tools=[_read_tool()], load_revision=lambda *_: None) — bounded by AC-4


@pytest.mark.asyncio
async def test_agentic_retrieve_fails_fast_without_tool_loop(agentic_toolkit, monkeypatch) -> None:
    """On a real tree, agentic_retrieve raises before candidate search and before any ask()."""
    toolkit, _, _ = agentic_toolkit
    client = NoLoopClient()
    toolkit._agentic_client_override = client
    # FILL IN: monkeypatch toolkit._agentic_search with a lambda that calls pytest.fail("candidate search reached");
    #   pytest.raises(ValueError, match="NoLoopClient") around `await toolkit.agentic_retrieve("t", "question")`;
    #   then assert client.ask_calls == 0 — bounded by AC-4


def test_agentic_client_clone_rejects_no_loop_adapter_client(tmp_path: Path) -> None:
    """The clone path (adapter client copied by clone_for_tools) is checked too."""
    toolkit = PageIndexToolkit(storage_dir=tmp_path, adapter=PageIndexLLMAdapter(client=NoLoopClient(), model="stub"))
    # FILL IN: pytest.raises(ValueError, match="supports_tool_loop=False") around toolkit._agentic_client() — bounded by AC-4
```
**Why**: the fixture-based test proves "before candidate search" on a real tree (the `_agentic_search` trap) —
a missing tree would not prove it. `NoLoopClient.ask` raising `AssertionError` makes any accidental LLM call loud.

### FILL IN checklist
- [ ] `test_agentic_retriever_rejects_no_loop_client` — one `pytest.raises`; bounded by AC-4
- [ ] `test_agentic_retrieve_fails_fast_without_tool_loop` — search trap + `pytest.raises` + `ask_calls == 0`; bounded by AC-4
- [ ] `test_agentic_client_clone_rejects_no_loop_adapter_client` — one `pytest.raises`; bounded by AC-4

---

## Acceptance Criteria

- [ ] `AgenticRetriever(client=<False client>, ...)` raises `ValueError` whose message contains the class name and `client_type` (spec AC-4).
- [ ] `PageIndexToolkit.agentic_retrieve` with such a client raises the same error before any `ask()` call and before candidate search, on both the override and the clone path (spec AC-4).
- [ ] `EvidenceBundle` / `StopReason` unchanged; every existing test in `test_agentic_retrieval.py` still passes (spec AC-7; `test_end_to_end_cited_evidence` keeps running the loop on `ScriptedToolLoopClient`).
- [ ] `ruff check` passes on every file this task touches.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py -q`

---

## Test Specification

See the append block above: `NoLoopClient(StubClient)` with `supports_tool_loop = False` and an `ask()` call
counter, plus `test_agentic_retriever_rejects_no_loop_client`, `test_agentic_retrieve_fails_fast_without_tool_loop`
and `test_agentic_client_clone_rejects_no_loop_adapter_client`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug client-tool-loop-capability --feature-id FEAT-848`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/client-tool-loop-capability.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/client-tool-loop-capability.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5380 client-tool-loop-capability verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
