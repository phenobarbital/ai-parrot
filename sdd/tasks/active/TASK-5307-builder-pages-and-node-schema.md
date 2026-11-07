# TASK-5307: Return per-page markdown from the builder; node schema fields

**Feature**: FEAT-840 — PageIndex Segment Store
**Spec**: `sdd/specs/pageindex-segment-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Part of spec §3 **Module 7**. Today `build_page_index` computes per-page markdown and throws it
away (`_extract_node_markdown` returns only the per-node map, `builder.py:1622-1639`). The
toolkit (TASK-5308) needs those pages to build the document revision. Also declares the new
optional node fields on `PageIndexNode`.

---

## Scope

- `_extract_node_markdown` returns `(node_markdown, pages)`; `pages` is `[]` for a `BytesIO`
  input or when extraction fails.
- Both return dicts of `build_page_index` gain `"_pages": pages` next to `"_node_markdown"`.
- `PageIndexNode` gains `doc_id`, `revision`, `span`, `owned` (all optional).
- Tests: `test_builder_pages.py` (new) and an append to `test_schemas.py`.

**NOT in scope**: using `_pages` (TASK-5308); changing the LLM pipeline or prompts.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py` | MODIFY | Keep pages |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py` | MODIFY | Node fields |
| `packages/ai-parrot/tests/knowledge/pageindex/test_builder_pages.py` | CREATE | `_extract_node_markdown` tests |
| `packages/ai-parrot/tests/knowledge/pageindex/test_schemas.py` | MODIFY | Node field test (append) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.pdf_to_markdown import build_node_markdown_map, extract_markdown_per_page  # builder.py:15
```

### Existing Signatures to Use
```python
# knowledge/pageindex/builder.py
async def build_page_index(doc, adapter, options=None, light_adapter=None, llm_concurrency=...) -> dict  # :1545
        node_markdown = _extract_node_markdown(doc, structure)            # :1596
            "_node_markdown": node_markdown,                              # :1610 (doc-description branch) and :1616 (final return)
def _extract_node_markdown(doc: str | BytesIO, structure: Any) -> dict[str, str]:   # :1622
    if not isinstance(doc, str): return {}                                # :1632-1633
    try: pages = extract_markdown_per_page(doc)                           # :1634-1635
    except (FileNotFoundError, ImportError, ValueError) as exc: ...; return {}   # :1636-1638
    return build_node_markdown_map(structure, pages)                      # :1639
# Only caller of _extract_node_markdown: builder.py:1596 (the copy under packages/ai-parrot/build/ is a stale build artifact; ignore it).

# knowledge/pageindex/schemas.py
class PageIndexNode(BaseModel):                                           # :118
    line_num: Optional[int] = None                                        # :128
    nodes: Optional[list[PageIndexNode]] = None                           # :129
    model_config = {"extra": "allow"}                                     # :131
```

### Does NOT Exist
- ~~`_pages` in the `build_page_index` result~~ — added here
- ~~`doc_id`/`revision`/`span`/`owned` on `PageIndexNode`~~ — added here (they already pass through via `extra="allow"`;
  declaring them documents and types them)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_schemas.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_builder_pages.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#build_page_index",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#_extract_node_markdown",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py#PageIndexNode"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every `return {}` in `_extract_node_markdown` becomes `return {}, []` — *because* the caller unpacks a tuple.
- `_pages` must be present in **both** return branches (`:1610` and `:1616`).
- `span: Optional[list[int]]`, `owned: Optional[list[list[int]]]` — JSON lists, not tuples, because the tree is JSON.
- Existing toolkit tests monkeypatch `build_page_index` with fakes that return no `_pages`; the toolkit treats a
  missing key as `[]` (TASK-5308), so nothing else changes.

---

## Implementation Blueprint

### Steps (in order)
1. Change `_extract_node_markdown` and its caller.
2. Add `_pages` to both return dicts.
3. Add the schema fields; write the tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py` (MODIFY)
```python
# MODIFY — `        node_markdown = _extract_node_markdown(doc, structure)` (verified: builder.py:1596)
# occurrences: 1 (verified: grep -c 'node_markdown = _extract_node_markdown(doc, structure)' builder.py)
        node_markdown, pages = _extract_node_markdown(doc, structure)

# MODIFY — `            "_node_markdown": node_markdown,` occurs TWICE (verified: grep -c → 2, lines 1610 and 1616).
# FILL IN: disambiguate — add `"_pages": pages,` after each occurrence:
#   :1610 inside `if opt.if_add_doc_description == "yes":` (preceded by `                    "structure": structure,`)
#   :1616 in the final `return {` (preceded by `            "structure": structure,`)

# MODIFY — the function at `def _extract_node_markdown(` (verified: builder.py:1622, occurrences: 1)
def _extract_node_markdown(
    doc: str | BytesIO,
    structure: Any,
) -> tuple[dict[str, str], list[tuple[int, str]]]:
    """Extract per-node markdown and the per-page markdown it was sliced from.

    Returns ``({}, [])`` for non-path inputs (``BytesIO``) or when extraction fails — callers
    persist whatever they get and fall back to summaries on retrieval.
    """
    # FILL IN: same body as today with `return {}, []` on the two early exits and
    #   `return build_node_markdown_map(structure, pages), pages` at the end — bounded by AC-1, AC-2
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py` (MODIFY)
```python
# AFTER — insert below `    line_num: Optional[int] = None` (verified: schemas.py:128)
# occurrences: 1 (verified: grep -c '    line_num: Optional\[int\] = None' schemas.py)
    doc_id: Optional[str] = None
    revision: Optional[str] = None
    span: Optional[list[int]] = None
    owned: Optional[list[list[int]]] = None
```

### FILL IN checklist
- [ ] `_extract_node_markdown` tuple returns; bounded by AC-1, AC-2
- [ ] both `_pages` insertions; bounded by AC-3

---

## Acceptance Criteria

- [ ] AC-1: with `extract_markdown_per_page` monkeypatched to return `[(1, "A"), (2, "B")]`, `_extract_node_markdown("x.pdf", structure)` returns the same node map as before and those pages.
- [ ] AC-2: a `BytesIO` input and an extraction `ValueError` both return `({}, [])`.
- [ ] AC-3: `grep -c '"_pages": pages,' builder.py` is 2.
- [ ] AC-4: `PageIndexNode(title="t", span=[0, 3], owned=[[0, 1]]).model_dump()` keeps both fields.
- [ ] `pytest packages/ai-parrot/tests/knowledge/pageindex/test_pdf_to_markdown.py` still passes; `ruff check` on both source files passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_builder_pages.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_schemas.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_pdf_to_markdown.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_builder_pages.py
from io import BytesIO

from parrot.knowledge.pageindex import builder


def test_extract_node_markdown_returns_pages(monkeypatch):
    monkeypatch.setattr(builder, "extract_markdown_per_page", lambda doc: [(1, "A"), (2, "B")])
    structure = [{"node_id": "0000", "start_index": 1, "end_index": 2}]
    node_md, pages = builder._extract_node_markdown("x.pdf", structure)
    assert node_md == {"0000": "AB"} and pages == [(1, "A"), (2, "B")]


def test_extract_node_markdown_fallbacks(monkeypatch):
    # FILL IN: BytesIO → ({}, []); extract raising ValueError → ({}, []) — AC-2
    ...

# packages/ai-parrot/tests/knowledge/pageindex/test_schemas.py  (append)
# def test_page_index_node_segment_fields(): FILL IN — AC-4
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-segment-store --feature-id FEAT-840`).
   Run tests with `PYTHONPATH=packages/ai-parrot/src` — the shared venv is editable-installed
   against the main checkout.
2. **Read the spec** at the path listed above for full context (§2 Overview is the design,
   §7 holds the splitter rules and the known risks).
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/pageindex-segment-store.json`.
4. **Verify the Codebase Contract** before writing code: re-run the `grep -c` of every MODIFY
   anchor; a count of `0` means drift — stop and report, do not invent an attachment point.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file.
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   within the constraint it names; touch only the files in *Files to Create / Modify*.
7. **Validate** — `ruff check --fix` on your files, then every command under *Validation Commands*.
8. **Commit code** (`feat(pageindex-segment-store): TASK-5307 — Return per-page markdown from the builder; node schema fields`), then close with
   `parrot sdd task close TASK-5307 pageindex-segment-store verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
