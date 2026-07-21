---
type: Wiki Overview
title: 'Feature Specification: AI-Parrot Loaders Metadata Standardization'
id: doc:sdd-specs-ai-parrot-loaders-metadata-standarization-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Loaders under `packages/ai-parrot-loaders/src/parrot_loaders/` produce
relates_to:
- concept: mod:parrot.loaders
  rel: mentions
- concept: mod:parrot.loaders.abstract
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
- concept: mod:parrot_loaders.audio
  rel: mentions
- concept: mod:parrot_loaders.basepdf
  rel: mentions
- concept: mod:parrot_loaders.basevideo
  rel: mentions
- concept: mod:parrot_loaders.csv
  rel: mentions
- concept: mod:parrot_loaders.database
  rel: mentions
- concept: mod:parrot_loaders.doc_converter
  rel: mentions
- concept: mod:parrot_loaders.docx
  rel: mentions
- concept: mod:parrot_loaders.epubloader
  rel: mentions
- concept: mod:parrot_loaders.excel
  rel: mentions
- concept: mod:parrot_loaders.html
  rel: mentions
- concept: mod:parrot_loaders.image
  rel: mentions
- concept: mod:parrot_loaders.imageunderstanding
  rel: mentions
- concept: mod:parrot_loaders.markdown
  rel: mentions
- concept: mod:parrot_loaders.pdf
  rel: mentions
- concept: mod:parrot_loaders.pdfmark
  rel: mentions
- concept: mod:parrot_loaders.pdftables
  rel: mentions
- concept: mod:parrot_loaders.ppt
  rel: mentions
- concept: mod:parrot_loaders.qa
  rel: mentions
- concept: mod:parrot_loaders.txt
  rel: mentions
- concept: mod:parrot_loaders.video
  rel: mentions
- concept: mod:parrot_loaders.videolocal
  rel: mentions
- concept: mod:parrot_loaders.videounderstanding
  rel: mentions
- concept: mod:parrot_loaders.vimeo
  rel: mentions
- concept: mod:parrot_loaders.web
  rel: mentions
- concept: mod:parrot_loaders.youtube
  rel: mentions
---

# Feature Specification: AI-Parrot Loaders Metadata Standardization

**Feature ID**: FEAT-125
**Date**: 2026-04-27
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.x (next minor)

---

## 1. Motivation & Business Requirements

### Problem Statement

Loaders under `packages/ai-parrot-loaders/src/parrot_loaders/` produce
`Document.metadata` payloads with inconsistent shape:

- Only **12 of 30** loaders go through `AbstractLoader.create_metadata`
  (csv, database, docx, doc_converter, epubloader, excel, html, image,
  markdown, pdf, ppt, qa). The rest build raw metadata dicts and miss
  the conventional fields the framework expects.
- **`source_type` and `category`** are absent from documents emitted by
  loaders that bypass `create_metadata` (audio, video, videolocal,
  videounderstanding, youtube, vimeo, imageunderstanding, pdfmark,
  pdftables, web, webscraping). `txt.py` calls `create_document` so it
  picks up defaults but never produces a meaningful `document_meta`.
- The **`document_meta`** sub-dict — when it appears — has wildly
  different keys per loader: `{language}`, `{language, topic_tags}`,
  `{language, title, topic_tags}`, `{start, end, id, language, title,
  topic_tags}`, `{table, schema, row_index, driver}`, `{description,
  summary, ...}`. Some loaders mix loader-specific fields *into* the
  top level instead of `document_meta`.
- There is **no `language` field** as a first-class loader attribute
  on `AbstractLoader`. Each video/audio loader maintains its own
  `_language` attribute, and document/text loaders have no language
  signal at all.
- There is **no auto-derived `title`** — when the caller doesn't
  provide one, downstream consumers have nothing to show.

This blocks the next milestone for **contextual retrieval**: prefixing
a small, predictable header (built from `document_meta`) onto chunks
before embedding, so vectors carry source/category/language/title
context without paying for an LLM rewrite per chunk. That technique
requires `document_meta` to be (a) present on every document, (b)
small and concise, and (c) carry the same well-known keys regardless
of which loader produced the document.

### Goals

- Make `AbstractLoader.create_metadata` the single entry point for
  metadata construction across **all** loaders. No raw dict emission.
- Add `language` as a first-class kwarg on `AbstractLoader.__init__`
  (default `"en"`) and thread it automatically into every
  `document_meta`.
- Auto-derive `title` from the source path (file: `path.stem`; URL:
  last meaningful URL segment) when the caller does not pass one.
- Define and enforce a **canonical `document_meta` shape** containing
  a denormalized copy of `source_type`, `category`, `type`, plus
  `language` and `title`. This sub-dict is the contextual-retrieval
  header source — it must be small and free of loader-specific noise.
- Keep loader-specific rich metadata (timestamps, table/row, video
  duration, OCR confidence, trafilatura fields, …) as **extra
  top-level fields** on `metadata`, NOT inside `document_meta`.
- Refactor the 13 loaders that currently bypass `create_metadata` so
  every emit-site routes through it. (`basepdf` and `basevideo` are
  base classes — they need helper additions, not refactors.)
- Add a non-fatal validator: if a Document escapes a loader without
  the canonical fields, log a warning and auto-fill defaults rather
  than raising. Hard failures are out of scope for this iteration.

### Non-Goals (explicitly out of scope)

- Implementing the contextual-retrieval header builder itself, or
  modifying chunking/embedding code. This spec only standardizes the
  metadata that the future header builder will consume.
- Changing `parrot.stores.models.Document` (still a Pydantic
  `{page_content, metadata}` model — no schema migration).
- LLM-driven enrichment (summarization, topic extraction). The whole
  point is to populate `document_meta` *without* an LLM call.
- Migrating already-stored documents in any vector store. New
  documents written after this feature ships carry the new shape;
  pre-existing rows are left as-is.
- Removing or renaming any existing top-level metadata field —
  backwards compatibility for downstream consumers is preserved.

---

## 2. Architectural Design

### Overview

`AbstractLoader.create_metadata` becomes the **only** sanctioned way
to build a `Document.metadata` dict inside a loader. Its contract is
extended to:

1. Always emit a canonical `document_meta` sub-dict containing exactly
   `{source_type, category, type, language, title}` — denormalized
   for contextual-retrieval consumption.
2. Accept `language` and `title` as first-class parameters; fall back
   to `self.language` (new instance attribute) and an auto-derived
   value from `path` respectively.
3. Pass through any additional `**kwargs` as **top-level** metadata
   fields (preserving rich loader-specific data).
4. Refuse to silently drop fields: if a caller passes
   `doc_metadata={"language": "es", "table": "plans"}`, `language`
   is folded into `document_meta` and `table` becomes a top-level
   key. The contract is documented and tested.

A new helper `AbstractLoader._validate_metadata(metadata: dict)` is
added and invoked from `create_document` (and from the result-collection
step in `_load_tasks`). It checks for the canonical fields and, when
something is missing, logs a warning and auto-fills defaults. It does
not raise.

The 13 loaders that build raw dicts are refactored emit-site by
emit-site to call `create_metadata`. Loader-specific fields move
either to top-level kwargs (e.g. `origin`, `vtt_path`, `table`,
`row_index`, `start_time`, `end_time`) or — only for fields that
are genuinely contextual — to `document_meta` via the `language`/
`title` channel.

### Component Diagram

```
                       AbstractLoader (extended)
                              │
                              ├── __init__(..., language="en")          # NEW first-class kwarg
                              ├── self.language                          # NEW attribute
                              ├── create_metadata(..., language=None,    # NEW params
                              │                   title=None)
                              │     └── builds canonical document_meta
                              ├── _derive_title(path) -> str             # NEW helper
                              └── _validate_metadata(meta) -> dict       # NEW non-fatal validator

  Concrete loaders that already use create_metadata        (no behavioral change beyond
   csv, database, docx, doc_converter, epubloader,         document_meta gaining
   excel, html, image, markdown, pdf, ppt, qa              language+title automatically)

  Concrete loaders refactored to use create_metadata
   audio, video, videolocal, videounderstanding,           (raw dicts → create_metadata
   youtube, vimeo, imageunderstanding, pdfmark,            with extras as top-level **kwargs)
   pdftables, web, webscraping, txt

  Base helpers (no concrete output)
   basepdf, basevideo                                       (gain a build_default_meta helper
                                                            for subclasses that override _load)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractLoader.__init__` (`packages/ai-parrot/src/parrot/loaders/abstract.py:44`) | extends signature | Adds `language: str = "en"`; sets `self.language`. |
| `AbstractLoader.create_metadata` (`abstract.py:717`) | extends signature & body | Adds `language`, `title` params; emits canonical `document_meta`; preserves extras at top level. |
| `AbstractLoader.create_document` (`abstract.py:750`) | extends body | Calls `_validate_metadata` before constructing the `Document`. |
| `AbstractLoader._load_tasks` (`abstract.py:567`) | extends body | Validates each returned `Document` once; warns on misses. |
| `parrot.stores.models.Document` (`packages/ai-parrot/src/parrot/stores/models.py:21`) | unchanged | Still a `BaseModel` with `page_content: str` and `metadata: dict`. |
| 13 concrete loaders under `packages/ai-parrot-loaders/src/parrot_loaders/` | refactor | All raw `metadata = {...}` dicts replaced by calls to `create_metadata`. |

### Data Models

`Document.metadata` (already `Dict[str, Any]`) will conventionally
hold the following shape after this feature:

```python
{
    # canonical top-level fields (always present)
    "url":          str,                 # path or http(s) URL
    "source":       str,                 # display origin (e.g. file basename)
    "filename":     str,                 # canonical filename or "file://..." form
    "type":         str,                 # doctype: e.g. "pdf", "audio_transcript", "db_row"
    "source_type":  str,                 # high-level kind: "file", "url", "database", "video", ...
    "created_at":   str,                 # "%Y-%m-%d, %H:%M:%S"
    "category":     str,                 # caller-defined bucket: "document", "transcript", ...

    # canonical contextual sub-dict (always present, small, no extras)
    "document_meta": {
        "source_type": str,    # mirrors top-level
        "category":    str,    # mirrors top-level
        "type":        str,    # mirrors top-level
        "language":    str,    # NEW; defaults to self.language ("en" by default)
        "title":       str,    # NEW; defaults to derived from path/url
    },

    # loader-specific extras (top-level, opaque to standard pipeline)
    # examples: "origin", "vtt_path", "table", "schema", "row_index",
    # "duration", "start_time", "end_time", "topic_tags", ...
    **loader_specific_extras,
}
```

`document_meta` is intentionally **closed-shape** at the standard
level: loaders MUST NOT shove arbitrary keys into it. Anything that
isn't one of the five canonical keys belongs at the top level.

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/loaders/abstract.py

class AbstractLoader(ABC):
    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        *,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'file',
        language: str = 'en',          # NEW
        **kwargs,
    ):
        ...
        self.language: str = language  # NEW

    def create_metadata(
        self,
        path: Union[str, PurePath],
        doctype: str = 'document',
        source_type: str = 'source',
        doc_metadata: Optional[dict] = None,
        *,
        language: Optional[str] = None,   # NEW; defaults to self.language
        title: Optional[str] = None,      # NEW; defaults to _derive_title(path)
        **kwargs,                         # extras → top-level metadata keys
    ) -> dict:
        ...

    def _derive_title(self, path: Union[str, PurePath]) -> str:
        """Best-effort title from a path, URL, or table reference."""
        ...

    def _validate_metadata(self, metadata: dict) -> dict:
        """Non-fatal: warns + auto-fills missing canonical fields."""
        ...
```

`create_document` keeps its existing signature; internally it now
passes `language` and `title` (when present in `kwargs`) through to
`create_metadata`, and runs `_validate_metadata` on the result before
wrapping it in a `Document`.

---

## 3. Module Breakdown

### Module 1: AbstractLoader contract changes
- **Path**: `packages/ai-parrot/src/parrot/loaders/abstract.py`
- **Responsibility**:
  - Add `language` kwarg + `self.language` attribute to `__init__`.
  - Extend `create_metadata` to accept `language`/`title`, build
    canonical `document_meta`, and forward extras to top level.
  - Add `_derive_title` helper.
  - Add `_validate_metadata` non-fatal validator.
  - Wire validator into `create_document` and into the post-`_load`
    collection loop in `_load_tasks`.
- **Depends on**: nothing in this spec. Existing `create_metadata` body
  is the starting point.

### Module 2: Refactor file/document loaders to use canonical metadata
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/{txt,html,csv,docx,excel,pdf,pdfmark,pdftables,ppt,markdown,doc_converter,epubloader,qa,image,imageunderstanding}.py`
- **Responsibility**: For each loader that currently bypasses or
  partially uses `create_metadata`, route every `Document` emit
  through `create_metadata`. Move loader-specific keys to top-level
  `**kwargs`. Loaders that already use `create_metadata` correctly
  (csv, docx, doc_converter, epubloader, excel, html, image,
  markdown, pdf, ppt, qa, database) are touched only to ensure they
  pass `language` (when known) and to drop any local `document_meta`
  values that violate the closed shape.
- **Depends on**: Module 1.

### Module 3: Refactor video/audio/web loaders to use canonical metadata
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/{audio,video,videolocal,videounderstanding,youtube,vimeo,web,webscraping}.py`
- **Responsibility**: These loaders construct several `Document`
  variants per source (transcript, srt, vtt, dialog chunk, scraped
  fragment, extracted table, …). Each emit-site is rewritten to call
  `create_metadata` with the appropriate `doctype`/`source_type`/
  extras. Loader-specific top-level keys (`origin`, `vtt_path`,
  `start_time`, `end_time`, `srt_path`, `summary_path`, …) are
  preserved as `**kwargs` to `create_metadata`. `_language` on these
  loaders is replaced by the inherited `self.language` (kept as a
  read-only alias if any external code still references `_language`).
- **Depends on**: Module 1.

### Module 4: Base loaders helper updates
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/{basepdf,basevideo}.py`
- **Responsibility**: `BaseVideoLoader` and `BasePDF` are abstract-ish
  base classes that other loaders extend. They get a small
  `build_default_meta(...)` helper that wraps `create_metadata` with
  video/PDF-typical defaults, so subclass refactors stay short. No
  behavioral change beyond providing the helper.
- **Depends on**: Module 1.

### Module 5: Tests for canonical metadata
- **Path**:
  - `packages/ai-parrot-loaders/tests/test_metadata_standardization.py` (new)
  - existing per-loader tests under `packages/ai-parrot-loaders/tests/`
    are updated where their fixtures assert specific metadata shapes.
- **Responsibility**: Verify (a) `create_metadata` always produces the
  canonical shape; (b) every loader emits documents that pass
  `_validate_metadata` without warnings; (c) `language` defaults
  correctly and propagates; (d) `title` is auto-derived for files,
  URLs, and DB references; (e) loader-specific extras land at top
  level, never inside `document_meta`.
- **Depends on**: Modules 1–4.

### Module 6: Documentation
- **Path**: loader-related docs under `docs/` (whichever existing
  page covers loaders + metadata; new short page if none).
- **Responsibility**: Document the canonical metadata shape, the
  `document_meta` contract, and the `language`/`title` defaults.
  Note that this is the foundation for upcoming contextual retrieval
  work and explain the invariant "extras live at top level, never in
  `document_meta`".
- **Depends on**: Modules 1–4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_create_metadata_canonical_shape` | 1 | `create_metadata` returns canonical top-level keys + closed `document_meta`. |
| `test_create_metadata_language_defaults_from_self` | 1 | When `language` kwarg is omitted, `self.language` is used. |
| `test_create_metadata_language_override` | 1 | Explicit `language=` overrides instance default. |
| `test_create_metadata_title_auto_derived_from_path` | 1 | File path → `path.stem`; URL → last meaningful segment; table-ref → `schema.table`. |
| `test_create_metadata_extras_become_top_level` | 1 | Arbitrary `**kwargs` land at top level, not inside `document_meta`. |
| `test_create_metadata_doc_metadata_legacy_input` | 1 | Legacy `doc_metadata={...}` callers still get a valid `document_meta` (canonical fields preserved; extras hoisted out). |
| `test_validate_metadata_warns_on_missing_canonical_field` | 1 | Manually-built dict missing `category` → warning logged + key auto-filled. |
| `test_validate_metadata_does_not_raise` | 1 | Validator never raises, even when given empty `{}`. |
| `test_text_loader_emits_canonical_metadata` | 2 | `TextLoader` produces canonical fields and `document_meta`. |
| `test_pdf_loader_emits_canonical_metadata` | 2 | Per-page documents from `PDFLoader` carry `document_meta` with correct `language` + derived `title`. |
| `test_audio_loader_canonical_metadata` | 3 | `AudioLoader` transcript/srt/vtt/dialog-chunk emits all carry the canonical shape; loader-specific keys (`origin`, `vtt_path`, …) live at top level. |
| `test_youtube_loader_canonical_metadata` | 3 | Same for `YoutubeLoader` per-chunk and full-doc variants; `topic_tags` lives at top level. |
| `test_webscraping_loader_canonical_metadata` | 3 | Each `content_kind` (fragment, video_link, navigation, table) carries the canonical shape; `content_kind` is a top-level extra. |
| `test_basevideo_helper_returns_canonical` | 4 | `BaseVideoLoader.build_default_meta()` returns canonical shape. |

### Integration Tests

| Test | Description |
|---|---|
| `test_all_loaders_produce_canonical_documents` | Parametrized integration test that instantiates every loader in `LOADER_REGISTRY` against a small fixture and asserts every returned `Document` passes `_validate_metadata` with zero warnings. |
| `test_document_meta_is_closed_shape` | For every loader fixture, `set(doc.metadata['document_meta'].keys()) == {'source_type','category','type','language','title'}`. No extras leak in. |
| `test_loader_specific_extras_preserved` | Pre-feature payloads (`origin`, `vtt_path`, `table`, `schema`, `row_index`, `topic_tags`, `start_time`, `end_time`, `content_kind`) still appear at the top level after refactor. |

### Test Data / Fixtures

```python
# tests/fixtures.py (new helpers)

import pytest
from pathlib import Path

@pytest.fixture
def sample_text_file(tmp_path) -> Path:
    p = tmp_path / "hello.txt"
    p.write_text("Hello, world.\n", encoding="utf-8")
    return p

CANONICAL_TOP_LEVEL = {
    "url", "source", "filename", "type",
    "source_type", "created_at", "category", "document_meta",
}
CANONICAL_DOC_META = {
    "source_type", "category", "type", "language", "title",
}
```

---

## 5. Acceptance Criteria

- [ ] `AbstractLoader.__init__` accepts `language: str = "en"` and
      stores it on `self.language`.
- [ ] `AbstractLoader.create_metadata` accepts `language` and `title`
      kwargs; canonical `document_meta` keys are exactly
      `{source_type, category, type, language, title}`.
- [ ] `AbstractLoader._derive_title` returns `path.stem` for a `Path`,
      a non-empty trailing segment for an `http(s)://...` URL, and
      `schema.table` for a `DatabaseLoader`-style ref.
- [ ] `AbstractLoader._validate_metadata` logs a warning (does **not**
      raise) when canonical fields are missing, and auto-fills sane
      defaults.
- [ ] All 30 loaders in `LOADER_REGISTRY` produce documents whose
      `metadata['document_meta']` matches the canonical closed shape
      with no extra keys.
- [ ] No loader emits a raw `metadata = {...}` dict — every emit-site
      goes through `create_metadata` (verified by grep in CI / spec
      review: `grep -nE "metadata\\s*=\\s*{" parrot_loaders/*.py`
      yields only allowed call sites).
- [ ] Pre-existing loader-specific fields (`origin`, `vtt_path`,
      `srt_path`, `summary_path`, `table`, `schema`, `row_index`,
      `driver`, `topic_tags`, `start_time`, `end_time`, `content_kind`,
      trafilatura keys, …) remain at the top level of `metadata`.
- [ ] All unit tests pass: `pytest packages/ai-parrot-loaders/tests/ -v`.
- [ ] No breaking changes to any existing loader public signature
      (only additive kwargs).
- [ ] Loader docs document the canonical shape and the
      "extras live at top level, never in `document_meta`" rule.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> All references below were verified by reading the listed files at
> the listed line numbers during spec authoring (2026-04-27).
> Implementation tasks MUST re-verify before editing — the working
> tree currently has unstaged changes in `vimeo.py`.

### Verified Imports

```python
# Used by every loader; confirmed via grep across packages/ai-parrot-loaders/.
from parrot.loaders.abstract import AbstractLoader            # abstract.py:36
from parrot.stores.models import Document                     # stores/models.py:21
from parrot.loaders import AbstractLoader                     # re-export, used by database.py:11
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/loaders/abstract.py
class AbstractLoader(ABC):
    extensions: List[str] = ['.*']                            # line 41
    skip_directories: List[str] = []                          # line 42

    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        *,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'file',
        **kwargs,
    ):                                                        # line 44
        # currently sets:
        self._source_type = source_type                       # line 74
        self.category: str = kwargs.get('category', 'document')  # line 76
        self.doctype:  str = kwargs.get('doctype',  'text')      # line 77
        # NOTE: NO self.language attribute today. This spec adds it.

    def create_metadata(
        self,
        path: Union[str, PurePath],
        doctype: str = 'document',
        source_type: str = 'source',
        doc_metadata: Optional[dict] = None,
        **kwargs,
    ):                                                        # line 717
        # current body builds:
        # {url, source, filename, type, source_type, created_at,
        #  category, document_meta: {**doc_metadata}, **kwargs}

    def create_document(
        self,
        content: Any,
        path: Union[str, PurePath],
        metadata: Optional[dict] = None,
        **kwargs,
    ) -> Document:                                            # line 750

    @abstractmethod
    async def _load(
        self,
        source: Union[str, PurePath],
        **kwargs,
    ) -> List[Document]:                                      # line 460
```

```python
# packages/ai-parrot/src/parrot/stores/models.py
class Document(BaseModel):                                    # line 21
    page_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

```python
# packages/ai-parrot-loaders/src/parrot_loaders/__init__.py
LOADER_REGISTRY: dict[str, str] = {                           # line 9
    "TextLoader": "parrot_loaders.txt.TextLoader",
    "CSVLoader":  "parrot_loaders.csv.CSVLoader",
    "ExcelLoader": "parrot_loaders.excel.ExcelLoader",
    "MSWordLoader": "parrot_loaders.docx.MSWordLoader",
    "HTMLLoader": "parrot_loaders.html.HTMLLoader",
    "MarkdownLoader": "parrot_loaders.markdown.MarkdownLoader",
    "PDFLoader": "parrot_loaders.pdf.PDFLoader",
    "QAFileLoader": "parrot_loaders.qa.QAFileLoader",
    "EpubLoader": "parrot_loaders.epubloader.EpubLoader",
    "PowerPointLoader": "parrot_loaders.ppt.PowerPointLoader",
    "DocumentConverterLoader": "parrot_loaders.doc_converter.DocumentConverterLoader",
    "BasePDF": "parrot_loaders.basepdf.BasePDF",
    "PDFMarkdownLoader": "parrot_loaders.pdfmark.PDFMarkdownLoader",
    "PDFTablesLoader": "parrot_loaders.pdftables.PDFTablesLoader",
    "WebLoader": "parrot_loaders.web.WebLoader",
    "BaseVideoLoader": "parrot_loaders.basevideo.BaseVideoLoader",
    "VideoLoader": "parrot_loaders.video.VideoLoader",

…(truncated)…
