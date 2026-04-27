# TASK-857: Refactor file/document loaders to use canonical metadata

**Feature**: FEAT-125 — AI-Parrot Loaders Metadata Standardization
**Spec**: `sdd/specs/ai-parrot-loaders-metadata-standarization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-855
**Assigned-to**: unassigned

---

## Context

This task covers **Module 2** of the spec. It refactors file-based and
document-oriented loaders to route all metadata through `create_metadata`.

There are two categories here:
1. **12 loaders already using `create_metadata`** (light touch): ensure they
   pass `language` when known and that no non-canonical keys leak into
   `doc_metadata`.
2. **Bypass loaders** (full refactor): `txt.py`, `pdfmark.py`, `pdftables.py`,
   `imageunderstanding.py` — replace raw `metadata = {...}` dicts with
   `create_metadata(...)` calls.

---

## Scope

### Light-touch loaders (already use create_metadata)
For each of: `csv.py`, `database.py`, `docx.py`, `doc_converter.py`,
`epubloader.py`, `excel.py`, `html.py`, `image.py`, `markdown.py`, `pdf.py`,
`ppt.py`, `qa.py`:
- Audit existing `create_metadata` / `doc_metadata` calls.
- If `doc_metadata` dict contains non-canonical keys (anything besides
  `source_type`, `category`, `type`, `language`, `title`), hoist them to
  top-level `**kwargs`.
- If the loader has language info available (e.g. `epubloader` from
  `dc:language`), pass it via `language=`.
- No structural changes needed if already compliant.

### Full refactor loaders
- **`txt.py`**: Currently uses `create_document` (line 25) which calls
  `create_metadata` internally. Ensure `language` and `title` thread through
  `create_document`'s `**kwargs`.
- **`pdfmark.py`**: Replace raw `base_metadata = {...}` (line 351) and
  `summary_metadata = {...}` (line 369) and `chunk_metadata = {...}` (line 393)
  with `create_metadata(...)` calls. Move page/heading-specific fields to
  top-level `**kwargs`.
- **`pdftables.py`**: Replace raw `metadata = {...}` (line 436) with
  `create_metadata(...)`. Move `page_index`, `table_index` etc. to top-level
  kwargs.
- **`imageunderstanding.py`**: Replace raw `base_metadata = {...}` (line 208),
  `main_doc_metadata` (line 238), `chunk_metadata` (line 252),
  `section_metadata` (line 275), `error_metadata` (line 299) with
  `create_metadata(...)` calls. Move model name, prompt, sections to top-level.

**NOT in scope**: Video/audio/web loaders (TASK-858/859/860). Base class helpers (TASK-856).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/txt.py` | MODIFY | Thread language/title through create_document |
| `packages/ai-parrot-loaders/src/parrot_loaders/pdfmark.py` | MODIFY | Replace 3 raw metadata dicts with create_metadata calls |
| `packages/ai-parrot-loaders/src/parrot_loaders/pdftables.py` | MODIFY | Replace raw metadata dict with create_metadata call |
| `packages/ai-parrot-loaders/src/parrot_loaders/imageunderstanding.py` | MODIFY | Replace 5 raw metadata dicts with create_metadata calls |
| `packages/ai-parrot-loaders/src/parrot_loaders/csv.py` | MODIFY | Audit doc_metadata for non-canonical keys (light touch) |
| `packages/ai-parrot-loaders/src/parrot_loaders/database.py` | MODIFY | Audit doc_metadata (light touch) |
| `packages/ai-parrot-loaders/src/parrot_loaders/docx.py` | MODIFY | Audit doc_metadata (light touch) |
| `packages/ai-parrot-loaders/src/parrot_loaders/doc_converter.py` | MODIFY | Audit doc_metadata (light touch) |
| `packages/ai-parrot-loaders/src/parrot_loaders/epubloader.py` | MODIFY | Audit + pass dc:language if available |
| `packages/ai-parrot-loaders/src/parrot_loaders/excel.py` | MODIFY | Audit doc_metadata (light touch) |
| `packages/ai-parrot-loaders/src/parrot_loaders/html.py` | MODIFY | Audit doc_metadata (light touch) |
| `packages/ai-parrot-loaders/src/parrot_loaders/image.py` | MODIFY | Audit doc_metadata (light touch) |
| `packages/ai-parrot-loaders/src/parrot_loaders/markdown.py` | MODIFY | Audit doc_metadata (light touch) |
| `packages/ai-parrot-loaders/src/parrot_loaders/pdf.py` | MODIFY | Audit doc_metadata (light touch) |
| `packages/ai-parrot-loaders/src/parrot_loaders/ppt.py` | MODIFY | Audit doc_metadata (light touch) |
| `packages/ai-parrot-loaders/src/parrot_loaders/qa.py` | MODIFY | Audit doc_metadata (light touch) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.loaders.abstract import AbstractLoader  # used by all loaders
from parrot.stores.models import Document            # stores/models.py:21
```

### Existing Signatures to Use
```python
# After TASK-855, AbstractLoader provides:
# create_metadata(path, doctype, source_type, doc_metadata, *, language=None, title=None, **kwargs)
# create_document(content, path, metadata=None, **kwargs)
# _validate_metadata(metadata) -> dict
# self.language: str  (defaults to "en")

# packages/ai-parrot-loaders/src/parrot_loaders/txt.py
class TextLoader(AbstractLoader):                                   # line 7
    async def _load(self, path: Path, **kwargs) -> list:            # line 13
        # line 25: return self.create_document(content, path)

# packages/ai-parrot-loaders/src/parrot_loaders/pdfmark.py — emit sites:
#   base_metadata = {...}                                           # line 351
#   summary_metadata = {...}                                        # line 369
#   chunk_metadata = {...}                                          # line 393

# packages/ai-parrot-loaders/src/parrot_loaders/pdftables.py — emit sites:
#   metadata = {...}                                                # line 436

# packages/ai-parrot-loaders/src/parrot_loaders/imageunderstanding.py — emit sites:
#   base_metadata = {...}                                           # line 208
#   main_doc_metadata = {...}                                       # line 238
#   chunk_metadata = {...}                                          # line 252
#   section_metadata = {...}                                        # line 275
#   error_metadata = {...}                                          # line 299
```

### Does NOT Exist
- ~~`TextLoader.create_metadata`~~ — TextLoader does not override `create_metadata`; it inherits from `AbstractLoader`.
- ~~`PDFMarkdownLoader.build_default_meta`~~ — will exist after TASK-856 on `BasePDF`, but this task does not depend on TASK-856. Use `create_metadata` directly.
- ~~`ImageUnderstandingLoader.language`~~ — no loader-level language attribute today; use `self.language` from `AbstractLoader` after TASK-855.

---

## Implementation Notes

### Refactor strategy per loader
For each raw `metadata = {...}` dict:
1. Identify `doctype`, `source_type`, and any `doc_metadata` values.
2. Replace with `self.create_metadata(path, doctype=..., source_type=..., language=..., title=..., extra_key=extra_val, ...)`.
3. Move loader-specific keys (page index, table index, heading, model name, etc.) to `**kwargs` (they become top-level metadata keys).

### Key Constraints
- Do NOT change any loader's `__init__` public signature (no new required args).
- All loaders that already call `create_metadata` correctly should need minimal changes.
- For `epubloader.py`, if EPUB metadata includes `dc:language`, extract and pass as `language=`.
- For `database.py`, the `_derive_title` should produce `schema.table` format — verify TASK-855 handles this, or pass `title=` explicitly.

### References in Codebase
- Each loader file under `packages/ai-parrot-loaders/src/parrot_loaders/`
- Grep for emit sites: `grep -nE "metadata\s*=\s*\{" packages/ai-parrot-loaders/src/parrot_loaders/*.py`

---

## Acceptance Criteria

- [ ] `txt.py` produces documents with canonical `document_meta`
- [ ] `pdfmark.py` — all 3 emit sites route through `create_metadata`
- [ ] `pdftables.py` — emit site routes through `create_metadata`
- [ ] `imageunderstanding.py` — all 5 emit sites route through `create_metadata`
- [ ] All 12 light-touch loaders produce `document_meta` with only canonical keys
- [ ] `epubloader.py` passes `dc:language` as `language=` when available
- [ ] No raw `metadata = {...}` dicts remain in any of the 16 loader files listed above
- [ ] Loader-specific extras (page_index, table_index, model_name, etc.) live at top level
- [ ] All tests pass: `pytest packages/ai-parrot-loaders/tests/ -v`
- [ ] No breaking changes to any loader public signature

---

## Test Specification

```python
# packages/ai-parrot-loaders/tests/test_file_loaders_metadata.py
import pytest
from pathlib import Path

CANONICAL_DOC_META_KEYS = {"source_type", "category", "type", "language", "title"}


class TestTextLoaderMetadata:
    def test_emits_canonical_metadata(self, sample_text_file):
        from parrot_loaders.txt import TextLoader
        loader = TextLoader(source=str(sample_text_file))
        # Would need async test runner for full load
        meta = loader.create_metadata(sample_text_file)
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS


class TestPDFMarkMetadata:
    def test_document_meta_closed_shape(self):
        from parrot_loaders.pdfmark import PDFMarkdownLoader
        loader = PDFMarkdownLoader()
        meta = loader.create_metadata(Path("/tmp/test.pdf"), doctype="pdf")
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS


class TestImageUnderstandingMetadata:
    def test_extras_at_top_level(self):
        from parrot_loaders.imageunderstanding import ImageUnderstandingLoader
        loader = ImageUnderstandingLoader()
        meta = loader.create_metadata(
            Path("/tmp/img.jpg"),
            doctype="image_analysis",
            source_type="file",
            model_name="gpt-4o"
        )
        assert "model_name" in meta
        assert "model_name" not in meta["document_meta"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-855 is in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm TASK-855 changes are present in `abstract.py`
   - Read each loader file to verify emit-site line numbers (they may have shifted)
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-857-refactor-file-document-loaders.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-04-27
**Notes**: All 16 loader files refactored. Full-refactor loaders (txt, pdfmark,
pdftables, imageunderstanding) now use `create_metadata()` at all emit sites.
Light-touch loaders (csv, database, docx, doc_converter, epubloader, excel,
image, markdown, pdf, ppt, qa) had non-canonical `doc_metadata` keys hoisted
to explicit kwargs. epubloader now extracts `dc:language` from EPUB metadata
when available. 17 new canonical-shape tests added in
`test_file_loaders_metadata.py`; all 17 pass. 7 pre-existing failures (5 excel,
2 webscraping) confirmed pre-existing via git stash — not caused by TASK-857.

**Deviations from spec**: none
