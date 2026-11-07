# TASK-5316: Bound `retrieve` output with `max_result_chars`

**Feature**: FEAT-842 — PageIndex Local MCP Toolkit
**Spec**: `sdd/specs/pageindex-local-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5314
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 3** (result sizing). `retrieve` joins the bodies of the top-k
nodes with no bound; in a stdio host every character lands in the model's context. A new
constructor option `max_result_chars` bounds `retrieve` (and only `retrieve`) with an
explicit truncation marker. The packaged template (TASK-5317) sets it to 24000; the class
default `None` keeps today's output byte-identical.

---

## Scope

- Add the keyword-only parameter `max_result_chars: Optional[int] = None` to
  `PageIndexToolkit.__init__` and store it as `self._max_result_chars`.
- Add `_bound_text(self, parts: list[str]) -> str` and make `retrieve` return
  `self._bound_text(parts)` instead of `"\n\n".join(parts)`.
- Add tests for `_bound_text` and the bounded `retrieve` to `test_toolkit_no_llm.py` (AC-6).

**NOT in scope**: bounding `get_tree` or `search` (spec §8, resolved: no); the template
value (TASK-5317); anything in `mcp/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `max_result_chars`, `_bound_text`, `retrieve` return |
| `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py` | MODIFY | `_bound_text` + bounded `retrieve` tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `1db2685b95`, **before** TASK-5314. TASK-5314 edits the same file
> first, so line numbers shift: re-locate each anchor with `grep -nF` and use the fresh
> line. A count of `0` means drift — stop and report.

### Verified Imports
```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit   # toolkit.py:63
# toolkit.py already has `Optional` from typing (:29)
```

### Existing Signatures to Use
```python
# knowledge/pageindex/toolkit.py (after TASK-5314)
class PageIndexToolkit(AbstractToolkit):
    def __init__(self, adapter=None, storage_dir=None, ..., lock_timeout_s: float = 30.0,
                 *, llm_client: Optional[AbstractClient] = None, **kwargs)   # created by TASK-5314
        self._use_embedding_walk = use_embedding_walk                        # :135 before TASK-5314
    @property
    def has_llm(self) -> bool                                                # created by TASK-5314, just above _ingester
    async def retrieve(self, tree_name: str, query: str, top_k: int = 5) -> str:   # :722
        ...
        parts: list[str] = []
        for cand in candidates:
            ...
            if body:
                parts.append(f"## {title}\n{body}")       # every part starts with a "## <title>" line
        return "\n\n".join(parts)                          # :757
```

`tests/knowledge/pageindex/test_toolkit_no_llm.py` is created by TASK-5314 (it has the
`_stub_tiktoken` autouse fixture and the `DOC` markdown constant).

### Does NOT Exist
- ~~`PageIndexToolkit._max_result_chars`~~, ~~`PageIndexToolkit._bound_text`~~ — created by this task
- ~~`max_result_chars` on `search`, `get_tree` or any tool signature~~ — constructor option only; tools keep their signatures (the LLM-facing schema must not change)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.__init__",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.retrieve"
  ]
}
```

---

## Implementation Notes

### Truncation rules (spec §2 "Result sizing" and §3 M3)
- `None` → `"\n\n".join(parts)` exactly (byte-identical, AC-6).
- Keep whole parts, in order, while the joined text fits in `max_result_chars`.
- If the **first** part alone is longer than the bound, cut it at the last paragraph break
  (`"\n\n"`) before the bound, but never inside its first line (`## title`). If no
  paragraph break exists after the title line, cut at the bound but keep the title line whole.
- When anything was dropped or cut, append
  `"\n\n[truncated: {n} more characters in {k} further sections — lower top_k or narrow the query]"`
  where `n` = characters not returned, `k` = parts not returned at all (a part cut in the
  middle is not counted in `k`).
- Output length ≤ `max_result_chars + len(marker)` (AC-6).

---

## Implementation Blueprint

### Steps (in order)
1. Add the constructor parameter and attribute — *why*: the factory passes YAML `kwargs` straight to the constructor.
2. Add `_bound_text` next to `has_llm` — *why*: a pure helper is unit-testable without a tree.
3. Switch `retrieve`'s return — *why*: only `retrieve` is bounded in this slice.
4. Add the tests — *why*: AC-6.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verify: grep -cF '        llm_client: Optional[AbstractClient] = None,' toolkit.py — line added by TASK-5314)
# AFTER — insert below `        llm_client: Optional[AbstractClient] = None,`
        max_result_chars: Optional[int] = None,
# FILL IN: docstring Args entry — "max_result_chars: upper bound on the text ``retrieve``
#   returns; ``None`` = unbounded." (spec §3 M1 skeleton text)

# occurrences: 1 (verified: grep -cF '        self._use_embedding_walk = use_embedding_walk' toolkit.py, :135 before TASK-5314)
# AFTER — insert below `        self._use_embedding_walk = use_embedding_walk`
        self._max_result_chars = max_result_chars

# occurrences: 1 (verify: grep -cF '    def _ingester(self) -> TwoStepIngester:' toolkit.py)
# BEFORE — insert above `    def _ingester(self) -> TwoStepIngester:` (below has_llm from TASK-5314)
    def _bound_text(self, parts: list[str]) -> str:
        """Join ``parts`` and apply ``max_result_chars``.

        Keeps whole parts while they fit; when the first part alone exceeds the bound it is cut
        at the last paragraph break before the bound, never inside its ``## title`` line. Appends
        ``"\\n\\n[truncated: {n} more characters in {k} further sections — lower top_k or narrow the query]"``.
        With ``max_result_chars`` None, returns ``"\\n\\n".join(parts)`` unchanged.
        """
        joined = "\n\n".join(parts)
        limit = self._max_result_chars
        if limit is None or len(joined) <= limit:
            return joined
        # FILL IN: build the kept text per the "Truncation rules" above — bounded by AC-6
        #   (whole parts first; first-part cut at "\n\n" after its title line; n and k for the marker)
        kept = ""
        dropped_chars = len(joined) - len(kept)
        dropped_parts = 0  # FILL IN: parts not returned at all
        return (
            f"{kept}\n\n[truncated: {dropped_chars} more characters in {dropped_parts} further sections"
            " — lower top_k or narrow the query]"
        )

# occurrences: 1 (verified: grep -cF '        return "\n\n".join(parts)' toolkit.py, :757 before TASK-5314)
# REPLACE (end of retrieve) with:
        return self._bound_text(parts)
```
**Why**: keyword-only placement after `llm_client` keeps positional calls intact. The marker
text is fixed by the spec and the docs (TASK-5319) quote it. Do not log the dropped text.

### `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py` (MODIFY)
```python
# APPEND at end of file
def test_bound_text_none_is_identity(tmp_path: Path) -> None:
    """AC-6: None keeps the output byte-identical."""
    # FILL IN: _bound_text(["## A\nx", "## B\ny"]) == "## A\nx\n\n## B\ny"


def test_bound_text_keeps_whole_parts_and_marks(tmp_path: Path) -> None:
    """AC-6: whole parts kept while they fit; marker names chars and sections dropped."""
    # FILL IN: max_result_chars small enough for 1 of 3 parts; result starts with part 1,
    #   ends with "lower top_k or narrow the query]", says "in 2 further sections"


def test_bound_text_cuts_first_part_after_title(tmp_path: Path) -> None:
    """AC-6: an oversized first part is cut at a paragraph break, never inside '## title'."""
    # FILL IN: first part = "## Title\n" + several "\n\n"-separated paragraphs; result starts with "## Title\n";
    #   len(result) <= max_result_chars + len(marker)


async def test_retrieve_is_bounded(tmp_path: Path) -> None:
    """AC-6 end to end: retrieve on a no-LLM toolkit honours max_result_chars."""
    pytest.importorskip("bm25s")
    # FILL IN: PageIndexToolkit(storage_dir=tmp_path, max_result_chars=200); insert DOC; retrieve -> ends with marker
```

### FILL IN checklist
- [ ] `_bound_text` kept-text algorithm and `dropped_parts` — bounded by "Truncation rules" + AC-6
- [ ] docstring Args entry for `max_result_chars`
- [ ] four test bodies — bounded by AC-6

---

## Acceptance Criteria

- [ ] AC-6 With `max_result_chars=N`, `retrieve` output length ≤ N + len(marker), ends with the marker when cut, never cuts a `## ` header line; with `None` the output is byte-identical to today.
- [ ] Existing `test_toolkit.py` still passes (default `None`).
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`

---

## Test Specification

See the MODIFY block for `test_toolkit_no_llm.py` above.

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5314 is `done` in `sdd/tasks/index/pageindex-local-mcp-toolkit.json`.
2. Re-locate every anchor with `grep -nF` (TASK-5314 shifted the lines); mark `in-progress`, commit only the index.
3. Implement from the blueprint; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit the two files; `parrot sdd task close TASK-5316 pageindex-local-mcp-toolkit verified`; fill the Completion Note; commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
