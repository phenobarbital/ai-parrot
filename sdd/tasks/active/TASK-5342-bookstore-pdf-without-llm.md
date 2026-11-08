# TASK-5342: Bookstore PDF ingest without an LLM (M8)

**Feature**: FEAT-845 — PageIndex Layout Structure Builder
**Spec**: `sdd/specs/pageindex-layout-structure.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5341
**Assigned-to**: unassigned

---

## Context

Spec §2 "Bookstore" and Module 8. Today `Bookstore.add_book` refuses every PDF when no LLM is
configured (`library.py:1130-1135`), because PDF structure needed the LLM. After TASK-5340/5341 a
PDF's structure comes from its bookmarks or printed headings, so Bookstore can index PDFs without a
model: deterministic structure, no summaries, no description. Without an LLM, `Bookstore._toolkit`
(`library.py:233-238`) hands the toolkit a `_NullAdapter`, so the toolkit believes it has a model —
Bookstore must therefore force `structure_mode="layout"` and both summary flags off on that path, so
`_NullAdapter` is never called. A `PDFStructureError` (unreadable file, no text layer, failed
extraction) becomes `BookstoreError("Cannot index <name>: <reason>")` so the CLI keeps its clean
error, and the outer `except BaseException` (`library.py:1230`) still removes the staging tree.

---

## Scope

- Import `PDFStructureError` from `parrot.knowledge.pageindex.layout` in `library.py`.
- Replace the PDF guard and `import_pdf` call with the spec M8 skeleton (mode by `has_llm`,
  summary flags by `has_llm`, `PDFStructureError` → `BookstoreError`).
- Replace `test_add_book_pdf_requires_llm` with `test_add_book_unreadable_pdf`; add
  `test_add_book_pdf_without_llm`.

**NOT in scope**: the `txt` branch's LLM guard (`library.py:1150+`, unchanged); carding; toolkit or
builder changes; the integration scenario where extraction fails mid-import (TASK-5345 covers the
Bookstore mapping end to end).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | PDF branch without the LLM guard; error mapping |
| `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` | MODIFY | Unreadable-PDF and no-LLM PDF tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# library.py (existing)
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, REPLACED_MARKER   # library.py:30

# test_library.py (existing)
from parrot.knowledge.bookstore.config import LibraryLocation                     # test_library.py:14
from parrot.knowledge.bookstore.library import (REPLACED_MARKER, _STAGING_MARKER, _STAGING_MAX_AGE_S,
                                                Bookstore, BookstoreError)        # test_library.py:15-21

# New in test_library.py:
import pymupdf                                                                    # 1.27.1 (pinned)
```

### Created by TASK-5333 (dependency, transitive via TASK-5340/5341)
```python
from parrot.knowledge.pageindex.layout import PDFStructureError   # class PDFStructureError(ValueError)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
class BookstoreError(RuntimeError): ...                                          # :111
class _NullAdapter:                                                              # :149
    model = None; client = None
    async def ask(self, *args, **kwargs) -> str                                  # returns ""
    async def ask_structured(self, *args, **kwargs)                              # raises RuntimeError
    async def ask_with_finish_info(self, *args, **kwargs)                        # raises RuntimeError (:174)
class Bookstore:
    def has_llm(self) -> bool  (property)                                        # :215
    def _toolkit(self, scope) -> PageIndexToolkit                                # :233 (_NullAdapter when no LLM, :238)
    def list_books(self) -> list[BookCard]                                       # :329
    async def add_book(self, file_path, scope="project", title=None, authors=None, topics=None,
                       force=False, *, relate=False) -> tuple[BookCard, str]     # :1060
        # :1129 `if fmt == "pdf":`; :1130-1135 guard (anchor :1132); :1136-1141 import_pdf call;
        # :1142 doc_description = result.get("doc_description") or ""
        # :1187 card_origin = "fallback" if not self.has_llm else "llm"
        # :1229-1236 except BaseException: delete staging tree, re-raise

# packages/ai-parrot/tests/knowledge/bookstore/test_library.py
@pytest.fixture def locations(tmp_path) -> list[LibraryLocation]                 # :27
@pytest.fixture def store_no_llm(locations) -> Bookstore                         # :47
async def test_add_book_pdf_requires_llm(store_no_llm, tmp_path)                 # :199 (replaced here)
# conftest.py:149-157 autouse stub of utils.count_tokens / md_builder.count_tokens (NOT get_encoder)
```

### Created by TASK-5341 (dependency)
```python
# PageIndexToolkit.import_pdf(..., structure_mode: str = "auto") -> dict  (result adds structure_source, ...)
```

### Does NOT Exist
- ~~`Bookstore.add_pdf`~~ / ~~`Bookstore.import_pdf`~~ — PDFs go through `add_book`
- ~~a `structure_mode` argument on `add_book`~~ — Bookstore chooses it from `has_llm`
- ~~`_NullAdapter.ask_json`~~ — not defined; the layout path never needs it
- ~~a guard against PDFs without an LLM after this task~~ — removed; only the `txt` guard remains

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/bookstore/library.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/bookstore/test_library.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.add_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#BookstoreError",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#_NullAdapter"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keep `with_summaries=self.has_llm, with_doc_description=self.has_llm` — with no LLM both are
  False, and with `structure_mode="layout"` the builder makes zero adapter calls (spec "Mode scope").
- Catch only `PDFStructureError`; anything else keeps propagating to the outer cleanup as today.
- The real-PDF test calls the real builder: stub `parrot.knowledge.pageindex.utils.get_encoder`
  (tiktoken may download its BPE; brief item 10) and the injection engine
  (`parrot.knowledge.pageindex.toolkit.get_injection_scoring_engine`) as `test_segment_import.py:35-37` does.

---

## Implementation Blueprint

### Steps (in order)
1. Add the `PDFStructureError` import — *why*: the mapping in step 2 needs it, and importing from `layout` (not the package root) avoids loading the toolkit twice.
2. Replace the PDF branch body — *why*: AC-13 / AC-19 (Bookstore part).
3. Replace the old test and add the no-LLM test; run the Validation Command — *why*: the old test asserted the guard this task removes.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)
```python
# (1) occurrences: 1 (verified: grep -c 'from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, REPLACED_MARKER' library.py)
# AFTER library.py:30
from parrot.knowledge.pageindex.layout import PDFStructureError

# (2) occurrences: 1 (verified: grep -c '                        "PDF ingest needs an LLM to detect and structure "' library.py)
#     and 1 (verified: grep -c '                result = await toolkit.import_pdf(' library.py)
# REPLACE library.py:1130-1141 (from `if not self.has_llm:` through the closing `)` of import_pdf);
# keep :1142 `doc_description = result.get("doc_description") or ""` unchanged below it
                try:
                    result = await toolkit.import_pdf(
                        tree_name=staging,
                        pdf_path=str(path),
                        with_summaries=self.has_llm,
                        with_doc_description=self.has_llm,
                        structure_mode="auto" if self.has_llm else "layout",
                    )
                except PDFStructureError as exc:
                    raise BookstoreError(f"Cannot index {path.name}: {exc}") from exc
```
**Why this shape**: verbatim spec M8 skeleton. `"layout"` without an LLM is what keeps the
`_NullAdapter` silent (the toolkit sees a non-None adapter, so `auto` would try the LLM fallback on a
low-confidence PDF and hit `_NullAdapter.ask_with_finish_info`). The `BookstoreError` re-raise still
passes through the outer `except BaseException` (`library.py:1229-1236`), which deletes the staging
tree — do not add a second cleanup.

### `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def test_add_book_pdf_requires_llm(store_no_llm, tmp_path):' test_library.py)
# REPLACE the whole test at test_library.py:198-211 (decorator through `await store_no_llm.add_book(pdf)`)
@pytest.mark.asyncio
async def test_add_book_unreadable_pdf(store_no_llm, tmp_path):
    """An unreadable PDF raises BookstoreError naming the file (AC-13; replaces the old LLM guard test)."""
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(BookstoreError, match="Cannot index book.pdf"):
        await store_no_llm.add_book(pdf)
    # FILL IN: assert no book was catalogued (store_no_llm.list_books() == []) — bounded by AC-19


def _headed_pdf(path):
    """Three pages, 10 pt body text and 16 pt headings, built with pymupdf."""
    import pymupdf

    # FILL IN: build the PDF (insert_text fontname "helv" for body, fontsize 16 for headings, set_toc
    #   optional), save to path, return path — bounded by brief item 11
    raise NotImplementedError


@pytest.mark.asyncio
async def test_add_book_pdf_without_llm(store_no_llm, tmp_path, monkeypatch):
    """No LLM: a real PDF is added with a deterministic structure and _NullAdapter is never called (AC-13)."""
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.get_encoder", lambda model="gpt-4o": None)
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.get_injection_scoring_engine", lambda force_reresolve=False: None
    )

    async def _never(*args, **kwargs):
        raise AssertionError("_NullAdapter must not be called on the PDF path")

    for name in ("ask", "ask_structured", "ask_with_finish_info"):
        monkeypatch.setattr(f"parrot.knowledge.bookstore.library._NullAdapter.{name}", _never)
    # FILL IN: card, status = await store_no_llm.add_book(_headed_pdf(tmp_path / "manual.pdf"));
    #   assert status == "added", card.card_origin == "fallback", the book's TOC is non-empty
    #   (deterministic layout/bookmarks/pages structure) — bounded by AC-13
    raise NotImplementedError
```
**Why this shape**: the unreadable case exercises the new mapping end to end (the builder raises
`UnreadablePDFError`, a `PDFStructureError`). The no-LLM case patches the three `_NullAdapter`
methods to fail loudly, which is the strongest proof that layout mode with summaries off makes no
model call. The conftest already stubs `count_tokens`; `get_encoder` is stubbed here because the real
builder now runs. If a module-level `_headed_pdf` helper name clashes with an existing one, rename it
(grep first).

### FILL IN checklist
- [ ] `test_add_book_unreadable_pdf` — no book catalogued after the error; bounded by AC-19
- [ ] `_headed_pdf` — synthetic PDF builder; bounded by brief item 11
- [ ] `test_add_book_pdf_without_llm` — add_book assertions; bounded by AC-13

---

## Acceptance Criteria

- [ ] AC-13: Bookstore without an LLM adds a real PDF (deterministic structure, `card_origin == "fallback"`) and never calls `_NullAdapter`; an unreadable PDF raises `BookstoreError` naming the file.
- [ ] AC-19 (Bookstore part): a `PDFStructureError` from the import is reported as `BookstoreError`; the staging tree is cleaned by the existing outer handler and no book is published.
- [ ] `test_add_book_pdf_requires_llm` no longer exists.
- [ ] All Validation Commands pass.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/bookstore/library.py packages/ai-parrot/tests/knowledge/bookstore/test_library.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_add_book_unreadable_pdf` | `BookstoreError` matching `Cannot index book.pdf`; no catalogued book |
| `test_add_book_pdf_without_llm` | `status == "added"`, `card_origin == "fallback"`, non-empty TOC, `_NullAdapter.ask*` never called |

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-layout-structure --feature-id FEAT-845`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5341 must be `"done"` in
   `sdd/tasks/index/pageindex-layout-structure.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/pageindex-layout-structure.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands as
   `PYTHONPATH=packages/ai-parrot/src pytest <file> -q` (never `uv sync` in the worktree)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5342 pageindex-layout-structure verified`
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
