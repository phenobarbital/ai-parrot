# TASK-2353: `DocumentAcquirer` — loader-backed local acquisition

**Feature**: FEAT-451 — `wikitoolkit ingest` — Binary Documents, URLs, and Metadata Frontmatter
**Spec**: `sdd/specs/wikitoolkit-ingest-documents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2351, TASK-2352
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec (§3) — the heart of FEAT-451, and the fix
for its headline defect. Today `wikitoolkit ingest` reads every document with
`read_text(encoding="utf-8", errors="ignore")` (cli.py:2474-2477), so a PDF
becomes mojibake, gets scored by the triage LLM, and can silently become a
nonsense wiki page.

`DocumentAcquirer.acquire()` replaces that read with a two-branch resolution:
plain text off disk (no optional dependency), or `parrot_loaders` for
everything else. Undecodable input raises `DocumentAcquisitionError` so the
caller can skip it — **garbage must never reach the LLM**.

---

## Scope

- ADD `DocumentAcquirer` to `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py`:

  ```python
  class DocumentAcquirer:
      def __init__(
          self,
          *,
          fetch_timeout: float = 30.0,
          max_bytes: int = 100 * 1024 * 1024,
          cache_dir: Path | None = None,
      ) -> None: ...

      async def acquire(self, ref: DocumentRef) -> AcquiredDocument: ...
  ```

- `acquire()` for a **local** ref (`ref.is_url is False`):
  - `ref.suffix in PLAIN_TEXT_EXTENSIONS` → read the file via
    `asyncio.to_thread(path.read_text, encoding="utf-8")`. On
    `UnicodeDecodeError`, raise `DocumentAcquisitionError`. Then apply
    `split_frontmatter()` — the parsed mapping feeds `DocumentMetadata`, the
    remaining body becomes `text`.
  - otherwise → resolve a loader class with a **lazy** `parrot_loaders` import
    inside a `try/except ImportError`. When the import fails, raise
    `DocumentAcquisitionError` naming the extensions readable without it.
    Instantiate the loader and extract markdown.
  - Populate `metadata.content_type` (from `mimetypes.guess_type`, falling
    back to the suffix) and `metadata.loader` (the loader class name, or
    `"plaintext"`).
  - For `.pdf`, set `metadata.page_count` from
    `pymupdf.open(path).page_count`. Wrap in `try/except` — a page count is
    nice-to-have, never a reason to fail acquisition.
  - Raise `DocumentAcquisitionError` when the extracted text is empty or
    contains a `\x00` byte (the mojibake tell).
- ADD a private `_normalize_metadata(...)` that maps a loader
  `Document.metadata` dict (the canonical FEAT-125 shape) into
  `DocumentMetadata`. Canonical keys map to named fields; every unmapped key
  lands in `extra` — nothing is silently dropped.
- Extend `tests/knowledge/wiki/test_documents.py`.

**NOT in scope**: URL fetching (TASK-2354 — leave a clearly-marked branch or
`NotImplementedError` for `ref.is_url`); any edit to `cli.py`, `ingest.py`,
`models.py`, `sources.py`; adding `ai-parrot-loaders` to any `pyproject.toml`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py` | MODIFY | Add `DocumentAcquirer` + `_normalize_metadata` |
| `tests/knowledge/wiki/test_documents.py` | MODIFY | Append acquirer tests |

---

## Codebase Contract (Anti-Hallucination)

> `parrot_loaders` is an OPTIONAL satellite distribution. `ai-parrot-loaders`
> **depends on** `ai-parrot` (`packages/ai-parrot-loaders/pyproject.toml:30`:
> `"ai-parrot>=0.26.1"`), so a module-level import here would be a circular
> dependency. **Import it lazily, inside the function, in a try/except.**

### Verified Imports

```python
import asyncio
import mimetypes
from pathlib import Path

# Core, safe at module level:
import pymupdf   # core dep — precedent: packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py:23

# The no-dependency plain-text extension set — REUSE, do not redefine:
from parrot.knowledge.graphindex.extractors.loader import PLAIN_TEXT_EXTENSIONS
#   packages/.../graphindex/extractors/loader.py:56-58
#   == {".md", ".markdown", ".txt", ".text", ".rst", ".mdx"}

# LAZY ONLY — inside acquire(), never at module scope:
#   from parrot_loaders.factory import get_loader_class
```

### Existing Signatures to Use

```python
# THE LAZY-IMPORT PRECEDENT — copy this shape exactly.
# packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py:667-704
@staticmethod
def _loader_for(uri: str) -> object | None:
    suffix = Path(uri).suffix.lower()
    if suffix in PLAIN_TEXT_EXTENSIONS:
        return PlainTextLoader(uri)
    try:
        from parrot_loaders.factory import get_loader_class
    except ImportError:
        logger.warning(
            "No loader for %s: ai-parrot-loaders is not installed "
            "(only %s are readable without it)", uri,
            ", ".join(sorted(PLAIN_TEXT_EXTENSIONS)),
        )
        return None
    try:
        return get_loader_class(suffix)(uri)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not build a loader for %s: %s", uri, exc)
        return None
```

```python
# packages/ai-parrot-loaders/src/parrot_loaders/factory.py
LOADER_MAPPING: dict[str, tuple[str, str]]        # line 11
#   '.pdf'->PDFLoader, '.docx'->MSWordLoader, '.pptx'/'.ppt'->PowerPointLoader,
#   '.xlsx'/'.xls'/'.xlsm'->ExcelLoader, '.html'->HTMLLoader, '.csv'->CSVLoader,
#   '.epub'->EpubLoader, '.md'/'.json'/'.xml'->MarkdownLoader, ...
def get_loader_class(extension: str)              # line 50
#   RETURNS MarkdownLoader as a FALLBACK for unknown extensions (lines 55-57).
#   It NEVER returns None.

# packages/ai-parrot-loaders/src/parrot_loaders/markdown.py
class MarkdownLoader(AbstractLoader):                                   # line 11
    def __init__(self, source=None, *, tokenizer=None, text_splitter=None,
                 source_type: str = 'file', enable_plugins: bool = True,
                 enable_ocr: bool = False, enable_audio: bool = False,
                 use_chapters: bool = False, use_sections: bool = False,
                 merge_consecutive_headers: bool = True,
                 min_section_length: int = 50, **kwargs)                # 35-50
    async def convert_to_markdown(self, path) -> str:                   # 554
        # PREFERRED extraction call: returns cleaned markdown text, or "" on error.
    async def _load(self, path: PurePath, **kwargs) -> List[Document]:  # 393
    def _extract_metadata_from_markdown(self, md_text, file_path) -> dict:  # 351
        # emits: title, word_count, header_count, table_count,
        #        code_block_count, link_count, image_count   (367-389)
    def validate_file_support(self, path) -> bool:                      # 539

# packages/ai-parrot/src/parrot/loaders/abstract.py
class AbstractLoader(ABC):                                              # 39
    @abstractmethod
    async def _load(self, source, **kwargs) -> list[Document]:          # 463-464
    def create_metadata(self, path, doctype='document', source_type='source',
                        doc_metadata=None, *, language=None, title=None,
                        **kwargs) -> dict:                              # 864
    # canonical TOP-LEVEL keys: url, source, filename, type, source_type,
    #   created_at, category, document_meta
    # document_meta CLOSED shape: {source_type, category, type, language, title}
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py  (TASK-2351/2352)
class DocumentRef(BaseModel): uri: str; is_url: bool; suffix: str
class DocumentMetadata(BaseModel): title/author/created_at/modified_at/
    page_count/word_count/language/content_type/source_url/loader/extra
class AcquiredDocument(BaseModel): ref: DocumentRef; text: str; metadata: DocumentMetadata
class DocumentAcquisitionError(Exception)
def split_frontmatter(text: str) -> tuple[dict[str, Any], str]
```

### Does NOT Exist

- ~~`get_loader_class()` returning `None`~~ — it falls back to `MarkdownLoader`
  for unknown extensions (factory.py:55-57). **Never write an `is None` guard
  on its return value.** The `None` in the `_loader_for` precedent comes from
  the `except ImportError` branch, not from `get_loader_class`.
- ~~`MarkdownLoader` exposing a page count~~ — `_extract_metadata_from_markdown`
  (markdown.py:351-390) emits `word_count`/`header_count`/`table_count`/
  `code_block_count`/`link_count`/`image_count` and **no page count**. Use
  `pymupdf.open(path).page_count` for PDFs.
- ~~`MarkdownLoader.load_url()` / `.from_uri()`~~ — not real.
- ~~`AbstractLoader.load()` returning a plain list of strings~~ — `from_path`
  (abstract.py:474) and `from_url` (507) return `list[asyncio.Task]`, not
  documents. Prefer `convert_to_markdown()` (markdown.py:554), or `await
  loader._load(path)` which returns `list[Document]`.
- ~~a module-level `import parrot_loaders` in core~~ — circular dependency.
- ~~`parrot.loaders.factory`~~ — the factory lives at `parrot_loaders.factory`.
  (A `sys.meta_path` shim redirects `parrot.tools.*`, **not** loaders.)
- ~~`requests` / `httpx`~~ — banned by CLAUDE.md.

---

## Implementation Notes

### Pattern to Follow

```python
async def acquire(self, ref: DocumentRef) -> AcquiredDocument:
    if ref.is_url:
        return await self._acquire_url(ref)     # TASK-2354
    path = Path(ref.uri)
    if ref.suffix in PLAIN_TEXT_EXTENSIONS:
        return await self._acquire_plaintext(ref, path)
    return await self._acquire_via_loader(ref, path)
```

### Key Constraints

- **Async-first**: every filesystem read and every loader call goes through
  `asyncio.to_thread` (the pattern already at cli.py:2474 and ingest.py:682).
  MarkItDown is synchronous and CPU-heavy — never call it on the event loop.
- **Keep the MarkItDown import inside `acquire()`.** Importing
  `parrot_loaders.markdown` pulls markitdown and its extractors; hoisting it
  would add that cost to `wikitoolkit query`/`page` startup.
- **Fail loudly, cheaply, and early.** `DocumentAcquisitionError` is raised
  *before* any LLM call. This is the whole point of the task — the current
  `errors="ignore"` is the actual defect being fixed.
- Do not swallow a loader exception into an empty string. `convert_to_markdown`
  already returns `""` on internal failure (markdown.py:566-568) — treat empty
  output as an acquisition failure, not as an empty document.
- `_normalize_metadata` must not drop unknown keys: everything unmapped goes
  into `extra`. Read `document_meta` (the closed FEAT-125 sub-dict) as well as
  the top level.
- Log one warning per skipped document, with the path and the reason.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py:667-704` — the lazy-import shape to copy.
- `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py:56-100` — `PLAIN_TEXT_EXTENSIONS` + `PlainTextLoader`.
- `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py:23,35` — pymupdf availability precedent.
- `packages/ai-parrot-loaders/src/parrot_loaders/markdown.py:554` — extraction call.

---

## Acceptance Criteria

- [ ] `.md` / `.txt` acquire correctly with `parrot_loaders` import forced to fail.
- [ ] `.pdf` dispatches through `get_loader_class(".pdf")`; the returned text is
      the loader's markdown, never raw bytes decoded with `errors="ignore"`.
- [ ] With `parrot_loaders` unavailable, a `.pdf` raises
      `DocumentAcquisitionError` — and **no mojibake string is ever returned**.
- [ ] A `.md` with leading YAML frontmatter yields `text` starting at the body
      and `metadata` populated from the block.
- [ ] Malformed frontmatter is left inline and does not raise.
- [ ] A PDF's `metadata.page_count` equals `pymupdf.open(path).page_count`.
- [ ] `metadata.content_type` and `metadata.loader` are always populated.
- [ ] Unmapped loader-metadata keys appear in `metadata.extra`, not dropped.
- [ ] Text containing `\x00`, or empty extracted text, raises
      `DocumentAcquisitionError`.
- [ ] No module-level `import parrot_loaders` anywhere in `documents.py`
      (assert with `grep`).
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_documents.py -v`
- [ ] `ruff check` and `mypy` clean.

---

## Test Specification

```python
# tests/knowledge/wiki/test_documents.py  (append)
import builtins
import pytest

from parrot.knowledge.wiki.documents import (
    DocumentAcquirer, DocumentAcquisitionError, DocumentRef,
)


@pytest.fixture
def no_parrot_loaders(monkeypatch):
    """Force `from parrot_loaders... import ...` to raise ImportError."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("parrot_loaders"):
            raise ImportError("simulated: ai-parrot-loaders not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


class TestAcquireLocal:
    async def test_plaintext_without_loaders(self, tmp_path, no_parrot_loaders):
        p = tmp_path / "a.md"
        p.write_text("# Title\nbody\n")
        doc = await DocumentAcquirer().acquire(
            DocumentRef(uri=str(p), suffix=".md")
        )
        assert "body" in doc.text
        assert doc.metadata.loader == "plaintext"

    async def test_strips_md_frontmatter(self, tmp_path):
        p = tmp_path / "a.md"
        p.write_text("---\ntitle: Contrato\nauthor: Legal\n---\n# Body\n")
        doc = await DocumentAcquirer().acquire(
            DocumentRef(uri=str(p), suffix=".md")
        )
        assert doc.text.lstrip().startswith("# Body")
        assert "title: Contrato" not in doc.text
        assert doc.metadata.title == "Contrato"
        assert doc.metadata.author == "Legal"

    async def test_binary_without_loaders_raises(self, tmp_path, no_parrot_loaders):
        p = tmp_path / "a.pdf"
        p.write_bytes(b"%PDF-1.4\n\x00\x01binary")
        with pytest.raises(DocumentAcquisitionError):
            await DocumentAcquirer().acquire(
                DocumentRef(uri=str(p), suffix=".pdf")
            )

    async def test_binary_uses_loader(self, tmp_path, monkeypatch, sample_pdf):
        doc = await DocumentAcquirer().acquire(
            DocumentRef(uri=str(sample_pdf), suffix=".pdf")
        )
        assert doc.text.strip()
        assert "\x00" not in doc.text
        assert doc.metadata.content_type == "application/pdf"

    async def test_pdf_page_count(self, sample_pdf):
        import pymupdf
        doc = await DocumentAcquirer().acquire(
            DocumentRef(uri=str(sample_pdf), suffix=".pdf")
        )
        assert doc.metadata.page_count == pymupdf.open(str(sample_pdf)).page_count

    async def test_empty_extraction_raises(self, tmp_path, monkeypatch):
        """convert_to_markdown returning '' is a failure, not an empty doc."""
        ...

    def test_no_module_level_loader_import(self):
        src = (
            "packages/ai-parrot/src/parrot/knowledge/wiki/documents.py"
        )
        text = open(src).read()
        head = text.split("class DocumentAcquirer")[0]
        assert "import parrot_loaders" not in head
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 Overview, §3 Module 2, §7).
2. **Check dependencies** — TASK-2351 and TASK-2352 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `builder.py:667-704` and
   `markdown.py:554` before implementing. If they moved, update this contract
   first, then implement.
4. **Update status** in `sdd/tasks/index/wikitoolkit-ingest-documents.json` → `"in-progress"`.
5. **Implement** following the scope and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-2353-document-acquirer-local.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude session 2026-08-23)
**Date**: 2026-08-23
**Notes**: Added `DocumentAcquirer` with `_acquire_plaintext` (read + strip
frontmatter via `split_frontmatter`) and `_acquire_via_loader` (lazy
`parrot_loaders.factory.get_loader_class` import, `loader._load()`,
`pymupdf` page-count for `.pdf`), plus `_normalize_metadata` and
`_metadata_from_mapping` helpers. `_acquire_url` raises `NotImplementedError`
pending TASK-2354. One real bug found and fixed during implementation:
`MarkdownLoader`/`PDFLoader` create_metadata emits a top-level
`content_type` kwarg meaning chunk-kind (`"full_document"`), which
collided with `DocumentMetadata.content_type`'s MIME-type meaning of the
same field name — excluded `content_type`/`loader` from the generic
catch-all mapping in `_normalize_metadata` via
`_LOADER_METADATA_RESERVED_KEYS` so both are always derived independently
(mimetypes / loader class name), never copied verbatim from loader
metadata. All 28 tests in `tests/knowledge/wiki/test_documents.py` pass (7
new `TestAcquireLocal` tests + 2 local fixtures: `no_parrot_loaders`,
`sample_pdf`); `ruff check` and `mypy` (targeted at `documents.py`) clean.

**Deviations from spec**: none — `sample_pdf` fixture was added locally in
`test_documents.py` rather than `tests/knowledge/wiki/conftest.py` since
this task's Files to Create/Modify list only names `documents.py` and
`test_documents.py`; the shared conftest fixture (per spec §4) is left for
TASK-2358 (integration tests), which is expected to consume it there.
