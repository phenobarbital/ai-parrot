# TASK-5471: PageIndex `pdf_backend` option and extraction routing

**Feature**: FEAT-875 — Optional PyMuPDF Layout for Bookstore PDF Ingestion
**Spec**: `sdd/specs/bookstore-pymupdf-layout.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5470
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. This adds `pdf_backend="legacy" | "pymupdf-layout"` (default `legacy`) as a recognized
`build_page_index(options=...)` key, dispatches extraction in `_layout_pages`, and exposes the option as
a keyword on `PageIndexToolkit.import_pdf`. `pdf_backend` is **orthogonal** to the existing
`structure_mode="auto" | "layout" | "llm"`. Do not conflate the two.

## Scope

- `ConfigLoader._DEFAULTS` gains `"pdf_backend": "legacy"`. The `_validate_keys` check would otherwise reject the key.
- `build_page_index` validates `pdf_backend` against `{"legacy", "pymupdf-layout"}` **before** any PDF
  work. It raises `ValueError` for an unknown name, and for `pymupdf-layout` with a `BytesIO` input
  (spec: explicit Layout for streams fails before processing). It then forwards the value to `_layout_pages`.
- `_layout_pages(doc, *, pdf_backend="legacy")`:
  - legacy: the existing call, which still passes `hdr_info=LayoutHeaders(profile)`, unchanged;
  - `pymupdf-layout`: `await extract_layout_pages(doc)` with **no** `hdr_info`.
  - Both paths keep `analyze_layout`, `segment_pages`, the empty-text check, and the log line.
- `PageIndexToolkit.import_pdf(..., *, pdf_backend="legacy")` puts the value into the builder `options`.
- Legacy requests must never import or initialize Layout. Import `extract_layout_pages` lazily inside the Layout branch.
- Add unit tests to `test_builder_layout.py` for defaults, validation, dispatch, and stream rejection (mocking `extract_layout_pages`).

**NOT in scope**: Bookstore manager or CLI (TASK-5472), real native extraction tests (TASK-5473), and any change to `structure_mode` semantics.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py` | MODIFY | `pdf_backend` default in `ConfigLoader._DEFAULTS` |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py` | MODIFY | Validation + `_layout_pages` dispatch |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `import_pdf(pdf_backend=)` keyword |
| `packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py` | MODIFY | Routing/validation unit tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.pageindex.pdf_layout_backend import extract_layout_pages   # created by TASK-5470
from parrot.knowledge.pageindex.layout import LayoutHeaders, LayoutProfile, PDFStructureError
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py:598,94,51 (already imported by builder.py:18)
from parrot.knowledge.pageindex.pdf_to_markdown import extract_markdown_per_page
# verified: builder.py:17
from parrot.knowledge.pageindex.segments import Segment, segment_pages   # verified: builder.py:27
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py:773-822
class ConfigLoader:
    _DEFAULTS = {..., "structure_mode": "auto", "structure_min_confidence": 0.6}   # lines 776-787
    def _validate_keys(self, user_dict: dict) -> None: ...   # raises ValueError on unknown keys
    def load(self, user_opt: dict | config | None = None) -> config: ...   # line 805

# packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py:1571
async def build_page_index(doc: str | BytesIO, adapter=None, options=None, light_adapter=None,
                           llm_concurrency: int = DEFAULT_LLM_CONCURRENCY) -> dict: ...
#   line 1579: opt = ConfigLoader().load(options)
#   line 1608-1609: if isinstance(doc, str):\n            profile, pages, segments = await _layout_pages(doc)
# builder.py:1653
_STRUCTURE_MODES = frozenset({"auto", "layout", "llm"})
# builder.py:1673
async def _layout_stage(stage: str, name: str, func: Any, *args: Any, **kwargs: Any) -> Any: ...   # runs func in a thread
# builder.py:1683
async def _layout_pages(doc: str) -> tuple[LayoutProfile, list[tuple[int, str]], list[Segment]]: ...

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:2150
async def import_pdf(self, tree_name: str, pdf_path: str, parent_node_id: Optional[str] = None,
                     with_summaries: bool = True, with_doc_description: bool = False,
                     doc_id: Optional[str] = None, structure_mode: str = "auto") -> dict[str, Any]: ...
#   line 2181: subtree = await build_page_index(  ... options={..., "structure_mode": structure_mode}, ...)
```

### Does NOT Exist

- No `pdf_backend` key, option, or keyword anywhere in `parrot/` today.
- No `pageindex/config.py`. Configuration is `ConfigLoader` in `utils.py`.
- `structure_mode="layout"` is local structure selection, **not** PyMuPDF Layout activation.
- `_layout_stage` runs its function in a **thread**. Do not route `extract_layout_pages` (a coroutine) through it.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py#ConfigLoader",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#build_page_index",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#_layout_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.import_pdf"
  ]
}
```

## Implementation Notes

### Key Constraints

- Keep every existing positional argument. Add the new parameter keyword-only at the end (spec §7).
- No backend may be chosen implicitly from import availability.
- Never mix one backend's text with the other backend's segment offsets. Both paths feed `segment_pages(pages)` from the same `pages`.

## Implementation Blueprint

### Steps (in order)

1. `utils.py`: add the default. Without it, `ConfigLoader.load({"pdf_backend": ...})` raises on an unknown key.
2. `builder.py`: add the `_PDF_BACKENDS` constant and validate early in `build_page_index`, so bad input fails before `_read_page_tokens` opens the PDF.
3. `builder.py`: rewrite `_layout_pages` with the dispatch.
4. `toolkit.py`: add the keyword and forward it.
5. Add the unit tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '"structure_min_confidence": 0.6,' packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py)
# AFTER — insert below `        "structure_min_confidence": 0.6,` (verified: utils.py:786, inside ConfigLoader._DEFAULTS)
        "pdf_backend": "legacy",
```

**Why:** `_validate_keys` rejects any option not in the defaults. When the YAML default path is used,
`_default_dict` comes from the file instead. FILL IN: confirm whether any shipped PageIndex YAML default
file must also gain the key, bounded by "`ConfigLoader.load` must accept `pdf_backend`".

### `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '_STRUCTURE_MODES = frozenset' builder.py)
# AFTER — insert below `_STRUCTURE_MODES = frozenset({"auto", "layout", "llm"})` (verified: builder.py:1653)
_PDF_BACKENDS = frozenset({"legacy", "pymupdf-layout"})
```

```python
# occurrences: 1 (verified: grep -c 'raise ValueError("structure_mode=.llm. needs an LLM adapter")' builder.py)
# AFTER — insert below `        raise ValueError("structure_mode='llm' needs an LLM adapter")` (verified: builder.py:1585)
    pdf_backend = getattr(opt, "pdf_backend", "legacy")
    if pdf_backend not in _PDF_BACKENDS:
        raise ValueError(f"Unknown pdf_backend {pdf_backend!r}; expected one of {sorted(_PDF_BACKENDS)}")
    if pdf_backend != "legacy" and not isinstance(doc, str):
        raise ValueError("pdf_backend='pymupdf-layout' requires a PDF file path, not a stream")
```

```python
# occurrences: 1 (verified: grep -c 'profile, pages, segments = await _layout_pages(doc)' builder.py)
# REPLACE line builder.py:1609
            profile, pages, segments = await _layout_pages(doc, pdf_backend=pdf_backend)
```

```python
# occurrences: 1 (verified: grep -c 'async def _layout_pages(doc: str)' builder.py)
# REPLACE the def line + the extraction line (verified: builder.py:1683 and :1687)
async def _layout_pages(
    doc: str, *, pdf_backend: str = "legacy"
) -> tuple[LayoutProfile, list[tuple[int, str]], list[Segment]]:
    """Analyze, extract, and segment a PDF without blocking the event loop.

    ``pdf_backend="legacy"`` keeps the custom ``LayoutHeaders`` heading detector;
    ``"pymupdf-layout"`` uses PyMuPDF Layout's native headings in an isolated child process.
    """
    name = _doc_label(doc)
    profile = await _layout_stage("analysis", name, analyze_layout, doc)
    if pdf_backend == "pymupdf-layout":
        from .pdf_layout_backend import extract_layout_pages  # lazy: legacy never imports Layout

        pages = await extract_layout_pages(doc)
    else:
        pages = await _layout_stage(
            "extraction", name, extract_markdown_per_page, doc, hdr_info=LayoutHeaders(profile)
        )
    # ... existing segmentation / empty-text check / logger.info unchanged ...
```

**Why:** the lazy import satisfies "no import or inference of Layout on legacy requests". The Layout
coroutine is awaited directly because `_layout_stage` would push it into a thread. FILL IN: add
`pdf_backend` to the existing `logger.info("Layout: ...")` line, bounded by spec §2 "backend ... logged".

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF 'structure_mode: str = "auto",' toolkit.py)
# AFTER — insert below `        structure_mode: str = "auto",` inside import_pdf (verified: toolkit.py:2158)
        *,
        pdf_backend: str = "legacy",
```

```python
# AFTER — insert below `                "structure_mode": structure_mode,` (verified: toolkit.py:2188)
                "pdf_backend": pdf_backend,
```

**Why:** keyword-only keeps every positional caller valid. Also add an `Args:` docstring line:
`pdf_backend: "legacy" | "pymupdf-layout" — PDF text extractor; independent of structure_mode.`

### `packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py` (MODIFY)

```python
# APPEND at end of file
# FILL IN: test_pdf_backend_defaults_to_legacy — ConfigLoader().load(None).pdf_backend == "legacy"
# FILL IN: test_unknown_pdf_backend_rejected_before_reading — ValueError, _read_page_tokens not called
# FILL IN: test_layout_backend_rejects_stream — BytesIO + pymupdf-layout -> ValueError
# FILL IN: test_layout_backend_dispatch_skips_layout_headers — monkeypatch extract_layout_pages; assert awaited,
#          extract_markdown_per_page NOT called
# FILL IN: test_legacy_backend_does_not_import_layout_module — "parrot.knowledge.pageindex.pdf_layout_backend"
#          absent from sys.modules after a legacy build (or patched to raise on import)
```

### FILL IN checklist

- [ ] YAML default file check
- [ ] Backend in the `Layout:` log line
- [ ] Toolkit `pdf_backend` docstring line
- [ ] Five unit tests

## Acceptance Criteria

- [ ] The default is `legacy`, and existing callers behave byte-identically.
- [ ] An unknown backend, or Layout with a stream, raises `ValueError` before any PDF processing.
- [ ] The Layout path awaits `extract_layout_pages` and never passes `hdr_info`. The legacy path still passes `LayoutHeaders`.
- [ ] Legacy requests never import `pdf_layout_backend`.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py -q`

## Test Specification

Mock-based tests only (no Layout package needed). Use `monkeypatch.setattr` on the
`parrot.knowledge.pageindex.pdf_layout_backend.extract_layout_pages` symbol.

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**: `parrot sdd worktree ensure --slug bookstore-pymupdf-layout --feature-id FEAT-875`
2. **Read the spec** at the path listed above.
3. **Check dependencies**: TASK-5470 must be `"done"`.
4. **Verify the Codebase Contract** before writing code.
5. **Update status** to `"in-progress"` and commit only the index file.
6. **Implement** from the blueprint, completing every `FILL IN`.
7. **Verify**: run the Validation Commands.
8. **Commit** only the files this task lists.
9. **Close** with `parrot sdd task close TASK-5471 bookstore-pymupdf-layout verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
