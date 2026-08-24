---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: `wikitoolkit ingest` — Binary Documents, URLs, and Metadata Frontmatter

**Feature ID**: FEAT-451
**Date**: 2026-08-23
**Author**: Jesus Lara (spec: Claude session 2026-08-23)
**Status**: approved
**Target version**: next minor
**Builds on**: FEAT-402 (`sdd/specs/supervised-wiki-ingestion.spec.md`)

---

## 1. Motivation & Business Requirements

### Problem Statement

`wikitoolkit ingest` (FEAT-402) already implements charter-driven,
supervised ingestion of a document corpus — triage, manifest, HITL
review, audit sampling. But its **content-acquisition layer is a plain
UTF-8 file read**:

```python
# cli.py:2474-2477  (_triage_all, inner function of `ingest`)
content = await asyncio.to_thread(
    doc_path.read_text, encoding="utf-8", errors="ignore"
)
```

```python
# ingest.py:666-682  (WikiIngestOrchestrator._load_source)
return await asyncio.to_thread(path.read_text, encoding="utf-8")
```

This has three consequences that block the intended use case — ingesting
a real "corporate digital life" corpus (contracts, reports, decks,
scanned filings) into the LLM Wiki:

1. **Binary documents are silently corrupted, not rejected.** A PDF or
   DOCX read with `errors="ignore"` yields mojibake. The triage router
   scores that garbage, the LLM writes a nonsense briefing, and — if it
   scores above threshold — a nonsense wiki page is created. There is no
   error, so the corruption is invisible until a human reads the page.
   `_load_source` (no `errors=`) is worse: it raises `UnicodeDecodeError`
   mid-pipeline, after triage has already spent LLM calls.
2. **Only a folder can be ingested.** The `folder` argument is
   `click.Path(exists=True, file_okay=False)` (cli.py:2281-2283) — a
   single document cannot be ingested at all, and a remote URL has no
   path into the command.
3. **Document metadata is discarded.** Author, page count, creation
   date, producing application, source URL — everything a document
   carries about itself — never reaches the wiki. `SourceManifestEntry`
   (models.py:159-224) records provenance about *the ingest run*
   (hash, mtime, decision, charter version) but nothing about *the
   document*.

Meanwhile the repository already owns a mature answer to (1) and (3):
`parrot_loaders.markdown.MarkdownLoader` wraps MarkItDown and converts
PDF, DOCX, PPTX, XLSX, HTML, EPUB, CSV, JSON, XML — plus OCR and audio
behind flags — into markdown, and `AbstractLoader.create_metadata()`
(abstract.py:864) already defines a canonical metadata shape (FEAT-125).
`graphindex/builder.py:667-704` already demonstrates the correct way for
core `ai-parrot` to reach that optional satellite distribution without
inverting the dependency.

This feature closes the gap: make `ingest` acquire content through the
loader layer, accept a file/folder/URL, and carry document metadata
through to the wiki page as YAML frontmatter.

### Goals

- **Loader-backed content acquisition.** `ingest` resolves a document
  loader by extension (reusing `parrot_loaders.factory.get_loader_class`)
  and extracts markdown text, so PDF / DOCX / PPTX / XLSX / HTML / EPUB
  are triaged and ingested on their real content. Plain-text formats keep
  reading straight off disk with no optional dependency required.
- **One source argument, three shapes.** `wikitoolkit ingest <SOURCE>`
  accepts a directory (recursive walk, today's behavior — unchanged), a
  single document path, or an `http(s)://` URL.
- **Document metadata extraction.** Author, title, page/word count,
  creation date, content type, and originating URL are extracted per
  document into a normalized `DocumentMetadata` model.
- **Existing `.md` frontmatter is honored.** When a markdown or plain-text
  source already carries leading YAML frontmatter, it is parsed as a
  *metadata source* and **stripped from the body handed to the triage
  LLM** — never fed to the model as prose.
- **Triage provenance travels with the page.** The FEAT-402 decision trail
  (`composite_score`, `decision`, `decision_source`, `charter_version`) is
  emitted in the page frontmatter alongside the descriptive document
  metadata, so a reader or agent can see *why* a page was admitted without
  querying the sources table.
- **Metadata persisted twice, for two audiences.**
  - *Machine/audit*: new additive columns on the `sources` table
    (`doc_metadata` JSON, `content_type`, `loader`) via the existing
    additive-migration mechanism.
  - *Reader/agent*: emitted as deterministic **YAML frontmatter** at the
    head of every generated wiki page body, reusing the OKF frontmatter
    projection conventions.
- **Failures are loud and cheap.** A document that cannot be decoded is
  skipped with a warning and recorded — never triaged as mojibake, and
  never charged an LLM call.
- **`build` stays untouched.** The deterministic, offline, no-LLM
  contract of `wikitoolkit build` / `repo_scan.py` is load-bearing for
  the git post-commit hook and is not modified by this feature (same
  hard non-goal as FEAT-402).

### Non-Goals (explicitly out of scope)

- **Operator-supplied metadata** — a `.meta.md` sidecar or a
  `--meta key=value` flag that injects/overrides metadata for a binary
  document. Considered and deliberately deferred; v1 metadata is
  **extracted from the document**, not authored by the operator.
- **Changing `wikitoolkit build`, `upsert`, or `repo_scan.py`** —
  inherited hard non-goal from FEAT-402 §1.
- **Changing the triage router, charter, manifest, or review flow.**
  `IngestTriageRouter.triage(path, content)` keeps its exact signature;
  this feature only changes *what `content` is* and *what travels
  alongside it*.
- **Crawling.** A URL is fetched as a single document. No link
  following, no sitemap expansion, no recursive site ingestion.
- **New OCR / audio / video ingestion paths.** Those loaders exist in
  `ai-parrot-loaders` behind extras; if installed and mapped they work
  by consequence, but no OCR-specific behavior is designed, tested, or
  promised here.
- **A metadata query surface.** Persisting `doc_metadata` makes later
  filtering possible; adding `wikitoolkit query --author=...` is
  explicitly future work.
- **Rewriting existing wiki pages.** Pages ingested before this feature
  keep their frontmatter-less bodies; no backfill migration is run.

---

## 2. Architectural Design

### Overview

The change is deliberately shaped as **one new module plus three narrow
call-site swaps**. All new logic lands in a new
`wiki/documents.py`; `cli.py` (2694 lines, hot file) receives an
argument-type change and a call swap, and `ingest.py` receives a
`_load_source` swap and a frontmatter injection point.

The pipeline becomes:

1. **Resolve** — `resolve_sources(source)` turns the CLI argument into a
   list of `DocumentRef` (a path or a URL, plus its suffix). Directory →
   today's `_discover_documents` walk; file → one ref; URL → one ref.
2. **Acquire** — `DocumentAcquirer.acquire(ref)` returns
   `AcquiredDocument(text, metadata)`:
   - plain-text suffix (`PLAIN_TEXT_EXTENSIONS`) → direct read, no
     optional dependency; any leading YAML frontmatter is parsed into
     `DocumentMetadata` and **stripped** from the returned `text`;
   - otherwise → `parrot_loaders.factory.get_loader_class(suffix)`,
     lazily imported, degrading to a warning + skip when
     `ai-parrot-loaders` is absent (exactly the `_loader_for` precedent);
   - URL → fetched to a temp file, then dispatched by the content type /
     suffix through the same two branches.
3. **Triage** — unchanged. `router.triage(path, text)` now receives real
   extracted markdown instead of raw bytes-as-text.
4. **Apply** — `WikiIngestOrchestrator.ingest()` re-acquires through the
   same `DocumentAcquirer` (so `_load_source` and triage agree on the
   text), stamps `doc_metadata` / `content_type` / `loader` onto the
   `SourceManifestEntry`, and prefixes each generated page body with
   `render_frontmatter(metadata, provenance)` — where `provenance` is
   built from the `ManifestDocEntry` already passed as `triage=` plus the
   `charter_version` argument `ingest()` already receives.

Content is acquired **twice** per admitted document (once for triage,
once for apply) — matching the existing code's shape, where `_triage_all`
and `_load_source` are already independent reads. A per-run acquisition
cache is an optimization, not a correctness requirement (see §7).

### Component Diagram

```
CLI: wikitoolkit ingest <SOURCE>
  │
  ├─ resolve_sources(SOURCE) ──→ [DocumentRef, ...]      (dir | file | URL)
  │
  ├─ (triage lane)                       ┌────────────────────────────┐
  │   for ref in refs:                   │   DocumentAcquirer         │
  │     acquire(ref) ───────────────────→│                            │
  │       └→ AcquiredDocument            │  suffix in PLAIN_TEXT_EXT? │
  │            .text ──→ IngestTriageRouter.triage(path, text)        │
  │            .metadata ──┐             │   yes → read_text()        │
  │                        │             │   no  → parrot_loaders     │
  │                        │             │          .factory          │
  │                        │             │          .get_loader_class │
  │                        │             │            (lazy import)   │
  │                        │             │   url → fetch → temp file  │
  │                        │             └────────────────────────────┘
  │                        │                        │
  │                        │                        └→ DocumentMetadata
  │                        ▼                            (author, pages,
  └─ (apply lane)   WikiIngestOrchestrator.ingest()      created_at, ...)
        ├─ _load_source ──→ DocumentAcquirer (same path)
        ├─ SourceCollectionManager  ──→ sources table
        │     + doc_metadata (JSON) + content_type + loader
        └─ _build_page_records
              └─ body = render_frontmatter(metadata, provenance) + body
                        (provenance ← triage entry + charter_version)
                                    │
                                    └→ WikiPageRecord.body → WikiStore → export
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot_loaders.factory.get_loader_class` | uses (lazy import) | Optional dependency. Same guard as `GraphIndexBuilder._loader_for` (builder.py:689-704). |
| `parrot_loaders.markdown.MarkdownLoader` | uses | `convert_to_markdown(path)` (markdown.py:554) is the single-purpose extraction call; `_extract_metadata_from_markdown` (markdown.py:351) is the metadata precedent. |
| `PLAIN_TEXT_EXTENSIONS` | reuses | Imported from `graphindex.extractors.loader` (loader.py:57) — the no-dependency read set. |
| `IngestTriageRouter.triage()` | calls (unchanged signature) | triage.py:304. Only its `content` argument changes meaning. |
| `WikiIngestOrchestrator._load_source()` | replaces body | ingest.py:666-682. Signature widens to accept a `DocumentRef`/URI. |
| `WikiIngestOrchestrator._build_page_records()` | extends | ingest.py:709-800. New `frontmatter` kwarg prefixed onto each `body`. |
| `SourceCollectionManager._migrate_sources_columns()` | extends | sources.py:804-821. New columns appended to the additive-migration dict. |
| `SourceManifestEntry` | extends | models.py:159. Three new optional fields; all default `None` so old rows load. |
| `parrot.knowledge.okf.frontmatter` | patterns from | `project_frontmatter` (frontmatter.py:101) is the determinism precedent (fixed key order, sorted lists, omit `None`). |
| `wikitoolkit build` / `repo_scan.py` | **untouched** | Hard non-goal. |

### Data Models

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py  (NEW)

class DocumentRef(BaseModel):
    """One resolved ingestion source: a local file or a remote URL."""

    uri: str                      # absolute path, or http(s):// URL
    is_url: bool = False
    suffix: str = ""              # lowercased, with dot; "" when unknown

class DocumentMetadata(BaseModel):
    """Normalized, loader-agnostic metadata about a source document.

    Every field is optional: a plain .txt yields almost none, a PDF
    yields most. Unknown loader-specific keys land in `extra` and are
    rendered under an `extra:` frontmatter block, never lost.
    """

    title: str | None = None
    author: str | None = None
    created_at: str | None = None      # ISO-8601 when parseable
    modified_at: str | None = None
    page_count: int | None = None
    word_count: int | None = None
    language: str | None = None
    content_type: str | None = None    # e.g. "application/pdf"
    source_url: str | None = None      # set only for URL sources
    loader: str | None = None          # e.g. "MarkdownLoader"
    extra: dict[str, Any] = Field(default_factory=dict)

class AcquiredDocument(BaseModel):
    """Text + metadata produced by the acquisition layer.

    `text` has any leading YAML frontmatter STRIPPED — whatever it
    carried is already folded into `metadata`.
    """

    ref: DocumentRef
    text: str
    metadata: DocumentMetadata

class TriageProvenance(BaseModel):
    """FEAT-402 decision trail, rendered into the page frontmatter.

    Built from the `ManifestDocEntry` (review.py:135) already handed to
    `WikiIngestOrchestrator.ingest()` as `triage=`, plus the
    `charter_version` argument that call already receives. Introduces no
    new plumbing — it only surfaces what `ingest()` already holds.
    """

    composite_score: float | None = None
    decision: str | None = None          # admit | archive | discard
    decision_source: str | None = None   # heuristic | model | human | auto
    charter_version: str | None = None

class DocumentAcquisitionError(Exception):
    """Raised when a document cannot be decoded or fetched.

    Callers SKIP the document (warn + record) rather than triaging
    undecodable content — never let mojibake reach the LLM.
    """
```

`SourceManifestEntry` (models.py:159) gains three optional fields:

```python
    doc_metadata: Optional[dict[str, Any]] = Field(
        default=None,
        description="FEAT-451: extracted DocumentMetadata as a dict. "
                    "None for sources ingested before FEAT-451.",
    )
    content_type: Optional[str] = Field(default=None, ...)
    loader: Optional[str] = Field(default=None, ...)
```

### New Public Interfaces

```python
# parrot/knowledge/wiki/documents.py

def resolve_sources(source: str) -> list[DocumentRef]:
    """Resolve a CLI SOURCE argument into concrete document refs.

    Accepts a directory (recursive walk — same rules as the existing
    `_discover_documents`: dotfiles and dot-directories skipped), a
    single file path, or an http(s) URL.
    """

class DocumentAcquirer:
    """Extracts markdown text + metadata from a DocumentRef."""

    def __init__(
        self,
        *,
        fetch_timeout: float = 30.0,
        max_bytes: int = 100 * 1024 * 1024,
        cache_dir: Path | None = None,
    ) -> None: ...

    async def acquire(self, ref: DocumentRef) -> AcquiredDocument:
        """Raises DocumentAcquisitionError on undecodable/unfetchable input."""

def render_frontmatter(
    metadata: DocumentMetadata,
    provenance: TriageProvenance | None = None,
) -> str:
    """Render deterministic YAML frontmatter for a wiki page body.

    Fixed key order, sorted collections, `None` fields omitted, and a
    trailing `---\n` — same determinism contract as
    `parrot.knowledge.okf.frontmatter.project_frontmatter`. Returns ""
    when every field is None (never emits an empty `---\n---\n` block).

    Descriptive document fields come first; `provenance` (when given) is
    rendered under a single nested `triage:` key so the descriptive and
    audit halves can never collide on a key name.
    """


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split leading YAML frontmatter off a text document.

    Returns ``(parsed_mapping, body_without_frontmatter)``, or
    ``({}, text)`` unchanged when there is no leading ``---`` block, when
    the block never terminates, or when it does not parse as a YAML
    mapping — malformed frontmatter is never a hard error, it is simply
    left inline.
    """
```

CLI surface (cli.py) — the argument type changes and two flags are added:

```
wikitoolkit ingest <SOURCE> [--dry-run|--review|--interactive|--auto] ...
                   [--recursive/--no-recursive]   # directory walk, default on
                   [--fetch-timeout SECONDS]      # URL fetch, default 30
```

`SOURCE` is a plain `str` argument (no longer `click.Path(file_okay=False)`)
so a URL can be passed; existence validation moves into `resolve_sources`,
which raises `click.ClickException` with the same clarity Click gave before.

---

## 3. Module Breakdown

### Module 1: `documents.py` — models + `resolve_sources`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py` (new)
- **Responsibility**: `DocumentRef`, `DocumentMetadata`, `AcquiredDocument`,
  `TriageProvenance`, `DocumentAcquisitionError`, and `resolve_sources()`. Pure, no I/O beyond
  `Path.rglob` / `Path.is_file`. Directory walking preserves the exact
  semantics of today's `_discover_documents` (cli.py:2093-2114).
- **Depends on**: nothing new.

### Module 2: `DocumentAcquirer` — loader-backed extraction
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py`
- **Responsibility**: `acquire()` — plain-text branch, loader branch
  (lazy `parrot_loaders` import, graceful skip when absent), `split_frontmatter()`
  applied to every text-branch document so pre-existing YAML frontmatter
  becomes metadata instead of LLM prose, and metadata normalization from
  `Document.metadata` into `DocumentMetadata`. PDF
  `page_count` is read via `pymupdf` (already a core dependency, used by
  `pageindex/pdf_to_markdown.py`) since MarkItDown does not expose it.
- **Depends on**: Module 1.

### Module 3: URL acquisition
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py`
- **Responsibility**: fetch an `http(s)` ref with **aiohttp** (never
  `requests`/`httpx` — CLAUDE.md hard rule) into a temp file, honoring
  `fetch_timeout` and `max_bytes`; derive the suffix from the
  `Content-Type` header, falling back to the URL path; set
  `metadata.source_url`; then dispatch through Module 2. Temp files are
  removed in a `finally`.
- **Depends on**: Module 2.

### Module 4: `render_frontmatter`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py`
- **Responsibility**: `render_frontmatter(metadata, provenance=None)` —
  deterministic YAML projection of `DocumentMetadata`, with
  `TriageProvenance` rendered under a nested `triage:` key. Fixed field
  order, `None` omitted, `extra` keys sorted, values escaped by
  `yaml.safe_dump`. Returns `""` when both inputs are fully empty. Also
  owns `split_frontmatter()` (the inverse), used by Module 2.
- **Depends on**: Module 1.

### Module 5: `SourceManifestEntry` + sources-table migration
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/models.py`,
  `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py`
- **Responsibility**: three new optional fields on `SourceManifestEntry`;
  three new entries in `_SOURCES_DECISION_COLUMNS`-style additive
  migration (a new `_SOURCES_DOCUMENT_COLUMNS` dict, applied by the same
  `_migrate_sources_columns` loop); JSON encode/decode of `doc_metadata`
  in `_upsert` (sources.py:486) and `_row_to_entry` (sources.py:547) via
  the existing `_optional_column` helper (sources.py:526); the same three
  fields mirrored on the Arango document path (`_doc_to_entry`,
  sources.py:735). A new `record_document_metadata()` writer method.
- **Depends on**: Module 1.

### Module 6: Orchestrator wiring
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py`
- **Responsibility**: `_load_source` delegates to `DocumentAcquirer`;
  `ingest()` accepts an optional pre-acquired `AcquiredDocument` (so the
  CLI can pass the triage-lane result and skip re-acquisition), persists
  metadata via Module 5, builds a `TriageProvenance` from the `triage=`
  entry and `charter_version` it already receives, and passes
  `frontmatter=` into `_build_page_records` (ingest.py:709), which
  prefixes it onto each `WikiPageRecord.body`. Every page derived from one
  source gets **identical** frontmatter (resolved §8) — no per-page
  `page_range` derivation. Frontmatter is prefixed to the **body only** —
  `summary` and `token_count` semantics are unchanged except that
  `token_count` now covers the frontmatter it actually stores.
- **Depends on**: Modules 2, 4, 5.

### Module 7: CLI wiring
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- **Responsibility**: `SOURCE` argument type change, `--recursive` and
  `--fetch-timeout` options, `_discover_documents` replaced by
  `resolve_sources`, `_triage_all` acquiring via `DocumentAcquirer`
  (skipping + warning on `DocumentAcquisitionError`), and a skipped-count
  line in the summary output. **Hot-file discipline**: no new logic in
  `cli.py` beyond argument handling and orchestration calls.
- **Depends on**: Modules 1-6.

### Module 8: Documentation
- **Path**: `documentation/parrot-wiki-cli.md`, `docs/wiki-claude-code.md`
- **Responsibility**: document the widened `SOURCE` argument, the
  supported formats table, the `ai-parrot-loaders` optional-dependency
  requirement for binary formats, and the page frontmatter contract.
- **Depends on**: Module 7.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_resolve_sources_directory` | 1 | Directory → recursive refs; dotfiles/dot-dirs skipped; ordering deterministic (matches `_discover_documents` output on the same tree). |
| `test_resolve_sources_single_file` | 1 | A file path → exactly one `DocumentRef`, `is_url=False`, suffix lowercased. |
| `test_resolve_sources_url` | 1 | `https://x/a.pdf` → one ref, `is_url=True`, `suffix=".pdf"`. |
| `test_resolve_sources_missing_path` | 1 | Non-existent path → `click.ClickException` (not a bare `FileNotFoundError`). |
| `test_acquire_plaintext_no_loaders` | 2 | `.md`/`.txt` acquired with `parrot_loaders` import forced to fail — still succeeds. |
| `test_acquire_binary_uses_loader` | 2 | `.pdf` dispatches to `get_loader_class(".pdf")`; returned text is the loader's markdown, not raw bytes. |
| `test_acquire_binary_without_loaders_raises` | 2 | `parrot_loaders` absent + `.pdf` → `DocumentAcquisitionError`, and **no** mojibake string returned. |
| `test_acquire_metadata_normalization` | 2 | Loader `Document.metadata` (canonical FEAT-125 shape) → `DocumentMetadata`; unmapped keys land in `extra`. |
| `test_acquire_pdf_page_count` | 2 | PDF fixture → `page_count` matches `pymupdf.open(path).page_count`. |
| `test_acquire_url_fetch` | 3 | aiohttp mocked; temp file written, suffix from `Content-Type`, `source_url` set, temp file removed afterwards. |
| `test_acquire_url_timeout` | 3 | Fetch timeout → `DocumentAcquisitionError`, no temp file left behind. |
| `test_acquire_url_size_cap` | 3 | Response exceeding `max_bytes` → `DocumentAcquisitionError`. |
| `test_split_frontmatter_roundtrip` | 4 | `---`-delimited YAML → `(mapping, body)`; body excludes the block. |
| `test_split_frontmatter_malformed` | 4 | Unterminated block / non-mapping YAML → `({}, text)` unchanged, no raise. |
| `test_acquire_strips_md_frontmatter` | 2 | `.md` with frontmatter → `text` starts at the body, `metadata.title`/`author` populated from the block. |
| `test_render_frontmatter_provenance` | 4 | `TriageProvenance` renders under a nested `triage:` key; descriptive keys unaffected. |
| `test_render_frontmatter_deterministic` | 4 | Same metadata → byte-identical output across calls; key order fixed. |
| `test_render_frontmatter_omits_none` | 4 | `None` fields absent from output; `extra` keys sorted. |
| `test_render_frontmatter_empty` | 4 | All-`None` metadata → `""` (no empty `---\n---\n`). |
| `test_render_frontmatter_escapes` | 4 | A title containing `:` and a newline round-trips through `yaml.safe_load`. |
| `test_sources_migration_additive` | 5 | Pre-FEAT-451 sqlite file opens; new columns added; existing rows intact with `doc_metadata=None`. |
| `test_source_entry_roundtrip_metadata` | 5 | `doc_metadata` dict survives `_upsert` → `_row_to_entry` as an equal dict. |

### Integration Tests

| Test | Description |
|---|---|
| `test_ingest_pdf_end_to_end` | PDF fixture → `--auto` ingest → page exists, body starts with `---`, frontmatter parses and carries `page_count` + `content_type`; sources row has `doc_metadata`. |
| `test_ingest_mixed_corpus` | Folder with `.md` + `.pdf` + `.docx` + one undecodable file → all decodable docs triaged, the bad one skipped-and-reported, exit code 0. |
| `test_ingest_single_file` | `wikitoolkit ingest ./contrato.pdf --dry-run` → manifest with exactly one entry. |
| `test_ingest_url` | Mocked aiohttp serving a PDF → page created with `source_url` in frontmatter. |
| `test_undecodable_never_reaches_llm` | Stub triage adapter asserts it is **never called** for the undecodable document (the anti-mojibake guarantee, asserted not assumed). |
| `test_build_unaffected` | `wikitoolkit build` output byte-identical with FEAT-451 code present (inherited FEAT-402 regression guard). |
| `test_ingest_page_carries_provenance` | `--auto` ingest → page frontmatter `triage:` block carries `composite_score`, `decision`, `decision_source`, `charter_version` matching the manifest entry. |
| `test_multi_page_pdf_identical_frontmatter` | A PDF split into several wiki pages → every page's frontmatter block is byte-identical. |
| `test_legacy_pages_unchanged` | Pages ingested before FEAT-451 keep frontmatter-less bodies after a re-open (no backfill). |

### Test Data / Fixtures

```python
# tests/knowledge/wiki/conftest.py additions

@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    """A tiny 2-page PDF with Author/Title set, written via pymupdf."""

@pytest.fixture
def undecodable_file(tmp_path) -> Path:
    """Random bytes with a .pdf suffix — must be skipped, never triaged."""

@pytest.fixture
def no_parrot_loaders(monkeypatch):
    """Force `import parrot_loaders...` to raise ImportError."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `wikitoolkit ingest <dir>` behaves exactly as before for a corpus of
      plain-text/markdown files (same manifest entries, same decisions).
- [ ] `wikitoolkit ingest <file.pdf> --dry-run` produces a manifest with one
      entry whose briefing reflects the PDF's real text content.
- [ ] `wikitoolkit ingest https://<host>/<doc>.pdf --dry-run` fetches, extracts,
      and triages the remote document.
- [ ] PDF, DOCX, PPTX, XLSX, HTML, and EPUB sources are extracted through
      `parrot_loaders`, not `read_text()`.
- [ ] A document that cannot be decoded is **skipped with a warning and
      counted in the run summary** — never triaged, and no LLM call is
      charged for it (asserted by `test_undecodable_never_reaches_llm`).
- [ ] With `ai-parrot-loaders` **not** installed, `ingest` still works for
      `PLAIN_TEXT_EXTENSIONS` and emits one clear warning per skipped
      binary document — it does not crash.
- [ ] Every wiki page generated by `ingest` begins with a YAML frontmatter
      block that `yaml.safe_load` parses, containing at least `title`,
      `content_type`, and `loader`; `None` fields are omitted.
- [ ] That frontmatter carries a nested `triage:` block with
      `composite_score`, `decision`, `decision_source`, and
      `charter_version` matching the manifest entry for that source.
- [ ] All pages derived from a single multi-page source carry **identical**
      frontmatter blocks.
- [ ] A `.md` source with leading YAML frontmatter has that block parsed
      into `DocumentMetadata` and **stripped** from the text passed to
      `IngestTriageRouter.triage()` — asserted directly against the stub
      adapter's received content, not inferred.
- [ ] Malformed frontmatter (unterminated block, non-mapping YAML) is left
      inline and never raises.
- [ ] `render_frontmatter` is byte-deterministic for equal input.
- [ ] `SourceManifestEntry` carries `doc_metadata`, `content_type`, and
      `loader`; they round-trip through both the sqlite and Arango backends.
- [ ] A pre-FEAT-451 wiki database opens without error and its existing
      rows are unchanged (additive migration only).
- [ ] `wikitoolkit build` output is byte-identical to pre-FEAT-451 output.
- [ ] No change to `repo_scan.py`, `build`, or `upsert`.
- [ ] `IngestTriageRouter.triage()` signature is unchanged.
- [ ] `cli.py` grows only argument handling + orchestration calls; all new
      logic lives in `documents.py`.
- [ ] No `requests` / `httpx` anywhere in the new code — URL fetching uses
      `aiohttp`.
- [ ] All unit tests pass: `pytest tests/knowledge/wiki/ -v`
- [ ] Docs updated: `documentation/parrot-wiki-cli.md` documents the widened
      `SOURCE` argument, the supported-format table, and the frontmatter
      contract.
- [ ] `ruff check` and `mypy` clean on all changed files.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against `dev` @ `91e49cf90` (2026-08-23). `cli.py` is a HOT file
> (2694 lines) — **re-anchor every line number before editing.**

### Verified Imports

```python
# Core wiki (all verified present)
from parrot.knowledge.wiki.models import SourceManifestEntry, WikiConfig, WikiPageCategory  # models.py:159, 52, 25
from parrot.knowledge.wiki.sources import SourceCollectionManager                            # sources.py:57
from parrot.knowledge.wiki.store import WikiPageRecord                                       # store.py:215
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator, IngestReport                # ingest.py:107, 83
from parrot.knowledge.wiki.triage import IngestTriageRouter, NoveltyScorer                   # triage.py:252, 67
from parrot.knowledge.wiki.review import ManifestDocEntry, ManifestRunHeader, ManifestWriter, ManifestReader  # review.py:135, 111, 172, 215
from parrot.knowledge.wiki.charter import load_charter, TriageExample, append_example        # used at cli.py:2374-2378

# The no-dependency plain-text extension set (REUSE, do not redefine)
from parrot.knowledge.graphindex.extractors.loader import PLAIN_TEXT_EXTENSIONS  # loader.py:57
#   == {".md", ".markdown", ".txt", ".text", ".rst", ".mdx"}

# Determinism precedent for frontmatter (patterns only — do NOT reuse
# ConceptFrontmatter itself: it is the OKF *concept* model, not a document model)
from parrot.knowledge.okf.frontmatter import project_frontmatter, parse_frontmatter  # frontmatter.py:101, 154

# OPTIONAL satellite — MUST be imported lazily inside the function, in a
# try/except ImportError, exactly like GraphIndexBuilder._loader_for
from parrot_loaders.factory import get_loader_class   # factory.py:50 — LAZY ONLY

# Core deps already in ai-parrot's pyproject (safe to import at module level)
import aiohttp
import yaml
import pymupdf          # used by pageindex/pdf_to_markdown.py:23
import click            # >=8.1.7
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py  (2694 lines @ 91e49cf90)

def _discover_documents(folder: Path) -> list[Path]:            # line 2093-2114
    """Flat recursive walk; skips any path with a dot-prefixed part."""
    return sorted(
        p for p in folder.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.parts)
    )                                                            # 2109-2113

def _resolve_charter_path(root: Path, charter_opt: str | None) -> Path:   # 2116
def _resolve_model_id(cli_value: str | None, env_name: str) -> str:       # 2144
def _build_triage_adapters(...)                                            # 2166
def _build_novelty_scorer(...)                                             # 2204
def _print_triage_summary(entries: list[Any]) -> None:                     # 2266

@wiki.command()                                                            # 2280
@click.argument(
    "folder", type=click.Path(exists=True, file_okay=False, path_type=Path)
)                                                                          # 2281-2283  <-- THE ARGUMENT TO WIDEN
def ingest(folder, path_, charter_opt, dry_run, review_opt, interactive_flag,
           auto_flag, extract_flag, lightweight_model_opt, model_opt,
           audit_rate, manifest_opt) -> None:                              # 2351-2364

    async def _triage_all(paths: list[Path], router: Any) -> list[Any]:    # 2472  <-- SWAP SITE 1
        for doc_path in paths:
            content = await asyncio.to_thread(
                doc_path.read_text, encoding="utf-8", errors="ignore"      # 2474-2477  <-- THE BUG
            )
            entry = await router.triage(doc_path, content)                 # 2478

    async def _apply_all(entries, wiki_config, charter_version) -> None:   # 2485
        await orch.ingest(entry.source_uri, wiki_config,
                          triage=entry, charter_version=charter_version)   # 2492-2497

    paths = _discover_documents(folder)                                    # 2544  <-- SWAP SITE 2
    entries = _run(_triage_all(paths, router))                             # 2545
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py

class WikiIngestOrchestrator:                                              # line 107
    def __init__(self, pi_toolkit, graph, sources, bookkeeper, *,
                 store=None, sync_graph=...)                               # 127
    async def ingest(
        self,
        source_path: str,
        wiki_config: WikiConfig,
        *,
        triage: Optional[ManifestDocEntry] = None,
        charter_version: Optional[str] = None,
    ) -> IngestReport:                                                     # 161-168
    async def _load_source(self, path: Path) -> str:                       # 666  <-- SWAP SITE 3
        return await asyncio.to_thread(path.read_text, encoding="utf-8")   # 682  (NO errors= → raises)
    async def _create_wiki_pages(self, content, tree_name, hint=None) -> dict[str, Any]:  # 684
    async def _build_page_records(
        self, tree_name: str, node_ids: list[str], source_id: str,
        fallback_title: str = "", fallback_summary: str = "",
        category_override: Optional[str] = None,
    ) -> list[WikiPageRecord]:                                             # 709-717  <-- ADD frontmatter kwarg
    def _load_body(self, loader, concept_id, node_id)                      # 815
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py

_SOURCES_DECISION_COLUMNS: dict[str, str] = {                              # 49-54
    "destination": "TEXT", "decision_source": "TEXT",
    "charter_version": "TEXT", "composite_score": "REAL",
}

class SourceCollectionManager:                                             # 57
    def add_source(self, path: Path) -> SourceManifestEntry:               # 171-211
    def mark_ingested(self, ...)                                           # 293
    def record_decision(self, ...)                                         # 332
    def _upsert(self, entry: SourceManifestEntry) -> None:                 # 486
    @staticmethod
    def _optional_column(row: sqlite3.Row, name: str) -> Any:              # 526
    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> SourceManifestEntry:            # 547
    @staticmethod
    def _doc_to_entry(doc: dict[str, Any]) -> SourceManifestEntry:         # 735  (Arango path)
    def _migrate_sources_columns(self) -> None:                            # 804-821
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class SourceManifestEntry(BaseModel):                                      # 159
    source_id: str; source_uri: str; file_hash: str; mtime: float
    ingested_at: str; pages_generated: list[str] = []
    status: str = "ingested"
    destination: Optional[str] = None
    decision_source: Optional[str] = None
    charter_version: Optional[str] = None
    composite_score: Optional[float] = None                                # 218-224

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class WikiPageRecord(BaseModel):                                           # 215
    concept_id: str; node_id: Optional[str] = None; title: str = ""
    category: str = "concept"; summary: str = ""; body: str = ""
    source_id: Optional[str] = None; token_count: int = 0
    origin: str = "ingest"; asserted_by: Optional[str] = None              # 234-243

# packages/ai-parrot/src/parrot/knowledge/wiki/triage.py
class IngestTriageRouter:                                                  # 252
    async def triage(self, path: Path, content: str) -> ManifestDocEntry:  # 304  (DO NOT CHANGE)
```

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
LOADER_MAPPING: dict[str, tuple[str, str]]                    # line 11 — .pdf/.docx/.pptx/.xlsx/.html/.md/.epub/…
def get_loader_class(extension: str)                          # line 50
#  NOTE: falls back to MarkdownLoader for UNKNOWN extensions (line 55-57)
#  — it NEVER returns None. Do not write `if get_loader_class(x) is None`.

# packages/ai-parrot-loaders/src/parrot_loaders/markdown.py
class MarkdownLoader(AbstractLoader):                                      # 11
    extensions = {'.pdf','.docx','.doc','.pptx','.ppt','.xlsx','.xls','.csv',
                  '.html','.htm','.xml','.json','.txt','.md', images…, audio…}  # 29-33
    def __init__(self, source=None, *, tokenizer=None, text_splitter=None,
                 source_type: str = 'file', enable_plugins: bool = True,
                 enable_ocr: bool = False, enable_audio: bool = False,
                 use_chapters: bool = False, use_sections: bool = False,
                 merge_consecutive_headers: bool = True,
                 min_section_length: int = 50, **kwargs)                   # 35-50
    def _extract_metadata_from_markdown(self, md_text, file_path) -> dict:  # 351
    #   → already parses YAML frontmatter, derives title from first H1, and
    #     emits word_count/header_count/table_count/code_block_count/
    #     link_count/image_count (367-389). REUSE these key names.
    async def _load(self, path: PurePath, **kwargs) -> List[Document]:      # 393
    async def convert_to_markdown(self, path) -> str:                       # 554  <-- PREFERRED extraction call
    def validate_file_support(self, path) -> bool:                          # 539
    def get_supported_formats(self) -> dict:                                # 521

# packages/ai-parrot/src/parrot/loaders/abstract.py
class AbstractLoader(ABC):                                                  # 39
    @abstractmethod
    async def _load(self, source: str | PurePath, **kwargs) -> list[Document]:  # 463-464
    async def from_path(self, path, recursive=False, **kwargs) -> list[asyncio.Task]:  # 474
    async def from_url(self, url: str | list[str], **kwargs) -> list[asyncio.Task]:    # 507
    async def load(self, ...)                                               # 610
    def create_metadata(self, path, doctype='document', source_type='source',
                        doc_metadata=None, *, language=None, title=None,
                        **kwargs) -> dict:                                  # 864
    #   canonical top-level keys: url, source, filename, type, source_type,
    #   created_at, category, document_meta   (FEAT-125, spec approved)
    #   document_meta closed shape: {source_type, category, type, language, title}
    def _validate_metadata(self, metadata: dict) -> dict:                   # 788
    def _derive_title(self, path) -> str:                                   # 736

# packages/ai-parrot/src/parrot/knowledge/okf/frontmatter.py
class ConceptFrontmatter(BaseModel)                                          # 35
def project_frontmatter(node: dict, tree_name: str) -> str                   # 101
def parse_frontmatter(text: str) -> ConceptFrontmatter                        # 154
#   Determinism contract (module docstring 1-22): pure function, fixed field
#   order, sorted tags, optional fields omitted when None, `---\n` delimiters.

# packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py
def extract_markdown_per_page(pdf_path: str | Path) -> list[tuple[int, str]]  # 35
#   Precedent that `pymupdf` + `pymupdf4llm` are core deps and importable.
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `resolve_sources()` | replaces `_discover_documents()` | call swap | `cli.py:2544` |
| `DocumentAcquirer.acquire()` | `_triage_all` inner fn | replaces `read_text` | `cli.py:2474-2477` |
| `DocumentAcquirer.acquire()` | `WikiIngestOrchestrator._load_source` | replaces body | `ingest.py:666-682` |
| `DocumentAcquirer` | `parrot_loaders.factory.get_loader_class` | lazy import in try/except | `builder.py:689-704` (precedent) |
| `DocumentAcquirer` | `PLAIN_TEXT_EXTENSIONS` | membership test | `extractors/loader.py:57` |
| `render_frontmatter()` | `WikiPageRecord.body` | string prefix in `_build_page_records` | `ingest.py:780-799` |
| `DocumentMetadata` | `SourceManifestEntry.doc_metadata` | `model_dump()` → JSON column | `models.py:159`, `sources.py:486` |
| new columns | `_migrate_sources_columns` | same additive `ALTER TABLE` loop | `sources.py:804-821` |
| `--fetch-timeout` | `DocumentAcquirer.__init__` | constructor kwarg | new |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.knowledge.wiki.documents`~~ — **you are creating it**. Verified
  absent from the `wiki/` package listing (arango_store, bookkeeper, charter,
  claude_code, cli, coding_agents, context, execution, export, file_store,
  ingest, languages, mcp_server, models, project, repo_scan, review, search,
  sources, store, toolkit, tools, triage, vault_scan).
- ~~`SourceManifestEntry.doc_metadata` / `.content_type` / `.loader`~~ — do not
  exist yet; you are adding them (models.py:189-224 has only the FEAT-402 four).
- ~~`parrot.knowledge.okf.frontmatter.split_frontmatter`~~ — the OKF module
  exports only `project_frontmatter` (frontmatter.py:101) and
  `parse_frontmatter` (frontmatter.py:154), and `parse_frontmatter` returns a
  `ConceptFrontmatter` **model** — not a `(mapping, body)` tuple, and it never
  returns the stripped body. Write `split_frontmatter` yourself in
  `documents.py`; the regex precedent is `MarkdownLoader.
  _extract_metadata_from_markdown` (markdown.py:364-372):
  `re.match(r'^---\n(.*?)\n---\n', md_text, re.DOTALL)`.
- ~~`WikiPageRecord.metadata` / `.frontmatter`~~ — no such field. Frontmatter is
  prefixed onto the existing `body` string; do not invent a new column.
- ~~`SourceCollectionManager.add_url()` / `add_source(url)`~~ — `add_source`
  takes a `Path` and calls `path.stat()` (sources.py:190, 200); it will raise
  `FileNotFoundError` on a URL. Register the **downloaded temp file**, or add
  a new method — do not pass a URL string to `add_source`.
- ~~`get_loader_class()` returning `None`~~ — it falls back to `MarkdownLoader`
  for unknown extensions (factory.py:55-57). Never write a `is None` guard on it.
- ~~`MarkdownLoader.load_url()` / `.from_uri()`~~ — not real. `AbstractLoader`
  has `from_url()` (abstract.py:507) which only wraps `_load(item)` in tasks;
  MarkItDown's own URL handling is not exercised anywhere in this repo. Fetch
  with `aiohttp` yourself.
- ~~`MarkdownLoader` exposing `page_count`~~ — `_extract_metadata_from_markdown`
  (markdown.py:351-390) emits `word_count`/`header_count`/`table_count`/
  `code_block_count`/`link_count`/`image_count` but **no page count**. Use
  `pymupdf.open(path).page_count` for PDFs.
- ~~a `parrot/` package at the repo root~~ — this is a uv workspace; core lives
  at `packages/ai-parrot/src/parrot/`.
- ~~`parrot.vectorstores`~~ — long gone; irrelevant here but a frequent
  hallucination in this repo.
- ~~`requests` / `httpx`~~ — banned by CLAUDE.md. Use `aiohttp`.
- ~~an `ingest --supervised` flag on `build`~~ — explicitly rejected by FEAT-402
  §1 Non-Goals. Do not add flags to `build`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Lazy optional import, graceful degradation.** Copy
  `GraphIndexBuilder._loader_for` (builder.py:667-704) verbatim in shape:
  plain-text branch first, `try: from parrot_loaders...` / `except ImportError:`
  with a warning naming the readable-without-it extensions. Core `ai-parrot`
  must never hard-depend on `ai-parrot-loaders` — the dependency runs the
  other way (`ai-parrot-loaders` requires `ai-parrot>=0.26.1`,
  `packages/ai-parrot-loaders/pyproject.toml:30`). A module-level
  `import parrot_loaders` would be a circular dependency.
- **Async-first, no blocking I/O.** Loader calls and file reads go through
  `asyncio.to_thread` (the pattern already used at cli.py:2474 and
  ingest.py:682). URL fetching uses `aiohttp` with an explicit
  `ClientTimeout`.
- **Determinism for frontmatter.** Follow the OKF contract
  (frontmatter.py:1-22): pure function, fixed field order, sorted
  collections, omit `None`, `yaml.safe_dump(..., sort_keys=False,
  allow_unicode=True, default_flow_style=False)`.
- **Additive migration only.** New sqlite columns go through the existing
  `PRAGMA table_info` guard loop (sources.py:812-821). Never `DROP`, never
  rewrite rows.
- **Hot-file discipline on `cli.py`.** 2694 lines, frequently touched by
  other features. Keep the diff to the argument declaration, two new
  options, and call swaps. Rebase on `dev` immediately before starting
  AND before committing.
- Google-style docstrings + strict type hints on everything new; Pydantic
  models for all structured data; `self.logger` / module logger, never
  `print`.

### Known Risks / Gotchas

- **Concurrent SDD sessions on `dev`.** `cli.py`, `ingest.py`, and
  `sources.py` are all hot. Rebase before starting and push the feature
  branch immediately after the first commit — a concurrent worker's
  `reset --hard origin/dev` will otherwise eat committed local work.
- **Mojibake must fail loudly, not silently.** The current
  `errors="ignore"` is the actual defect. Removing it without adding an
  explicit skip path would turn silent corruption into a mid-run crash
  after LLM spend. `DocumentAcquisitionError` must be caught in
  `_triage_all`, counted, and reported — the run continues.
- **Triage/apply text divergence.** `_triage_all` and `_load_source`
  acquire independently today. If a loader is non-deterministic (OCR,
  LLM-assisted extraction), the triaged text and the ingested text can
  differ. Mitigation: pass the already-acquired `AcquiredDocument` from
  the triage lane into `orch.ingest()` for the `--interactive` / `--auto`
  paths. `--review` re-acquires by necessity (a fresh process) — document
  this, do not pretend otherwise.
- **`--review` re-acquisition cost.** A `--review` pass over a large PDF
  corpus re-runs extraction for every admitted document. Acceptable for
  v1; a content-addressed acquisition cache under
  `<storage_dir>/ingest-cache/` is the obvious follow-up.
- **URL security.** Fetching an operator-supplied URL is an SSRF surface.
  v1 mitigations: `http(s)` schemes only, an explicit timeout, a
  `max_bytes` cap, and no redirect-following to non-http(s) schemes. This
  is an operator-run CLI, not a server endpoint — do not over-engineer,
  but do not omit the caps either.
- **Temp-file lifetime.** URL downloads must be removed in a `finally`,
  including on `DocumentAcquisitionError`.
- **`add_source` cannot take a URL** (it calls `path.stat()`,
  sources.py:200). For URL sources, register the downloaded temp file and
  overwrite `source_uri` with the original URL — otherwise the manifest
  records a path that no longer exists.
- **Frontmatter and `token_count`.** `_build_page_records` computes
  `token_count=estimate_tokens(body or summary)` (ingest.py:797). Prefix
  the frontmatter **before** that call so the count reflects what is
  actually stored.
- **Frontmatter must not confuse re-ingestion.** `MarkdownLoader.
  _extract_metadata_from_markdown` (markdown.py:364-372) parses leading
  frontmatter. If an exported wiki page is ever re-ingested, its own
  emitted frontmatter would be read back as source metadata. Harmless in
  v1 (values are consistent), but worth a comment at the emission site.
- **MarkItDown is heavy.** Importing `parrot_loaders.markdown` pulls
  markitdown and its transitive extractors. Keep the import inside
  `acquire()` so `wikitoolkit query`/`page` startup latency is unaffected.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `ai-parrot-loaders` | `>=0.x` (**optional**) | PDF/DOCX/PPTX/XLSX/HTML/EPUB extraction. Not added to `ai-parrot` dependencies — lazily imported, degrades to plain-text-only. |
| `aiohttp` | existing core dep | URL fetching (CLAUDE.md bans `requests`/`httpx`). |
| `PyYAML` | existing core dep | Frontmatter rendering (already used at frontmatter.py:26). |
| `pymupdf` | existing core dep | PDF `page_count` (precedent: `pdf_to_markdown.py:23`). |

No new entries in any `pyproject.toml` are required.

---

## 8. Open Questions

Resolved during spec Q&A (2026-08-23, *Owner: Jesus Lara*):

- [x] Which direction should the YAML frontmatter flow? — *Resolved*:
      **Output only.** Loader-extracted metadata is emitted as frontmatter
      onto the generated wiki page. Operator-supplied input (a `.meta.md`
      sidecar or `--meta key=value`) was offered and **not** selected — it
      is a Non-Goal for v1 (§1).
- [x] What should `ingest` accept as its source argument? — *Resolved*:
      **folder + single file + URL.** A `--from-list` bulk file was offered
      and not selected.
- [x] How should extracted metadata be persisted? — *Resolved*:
      **both** — a `doc_metadata` JSON column (plus `content_type`,
      `loader`) on `SourceManifestEntry`, **and** page frontmatter.

Resolved on spec approval (2026-08-23, *Owner: Jesus Lara*):

- [x] Should an existing `.md` source's own YAML frontmatter be parsed as a
      *metadata source* (feeding the emitted frontmatter and stripped from
      the body the LLM sees), or left inline as body text? — *Resolved*:
      **adopt now**, in v1. Folded into §1 Goals, §2 acquire step, Modules
      2 and 4, the `split_frontmatter()` interface, §4 and §5.
- [x] Should the frontmatter carry the FEAT-402 triage provenance
      (`composite_score`, `decision_source`, `charter_version`) alongside
      the document metadata? — *Resolved*: **yes, carried**, under a nested
      `triage:` key. Folded into `TriageProvenance`, `render_frontmatter`'s
      signature, Modules 4 and 6, §4 and §5.
- [x] For a multi-page source that PageIndex splits into several wiki
      pages, identical frontmatter or a derived per-page `page_range`? —
      *Resolved*: **identical** on every page. Folded into Module 6, §4
      and §5.

Still open:

- [ ] Is a content-addressed acquisition cache under
      `<storage_dir>/ingest-cache/` wanted in v1, or deferred? Deferred is
      assumed. — *Owner: implementation*

---

## Worktree Strategy

**Isolation unit**: `per-spec` — one worktree, tasks run sequentially.

Modules 1-4 all land in the same new file (`documents.py`) and Modules 6-7
edit hot shared files (`ingest.py`, `cli.py`), so parallel worktrees would
conflict on every task. Sequential execution in one worktree is correct here.

```bash
git checkout dev && git pull --ff-only origin dev
git worktree add -b feat-451-wikitoolkit-ingest-documents \
  .claude/worktrees/feat-451-wikitoolkit-ingest-documents HEAD
```

**Cross-feature dependencies**:
- **FEAT-402** (`supervised-wiki-ingestion`) — must be merged to `dev` first.
  Verified present at `91e49cf90`: the `ingest` command exists at cli.py:2280.
- **FEAT-450** (`wiki-namespaces`) is in flight and also touches the wiki
  package. Coordinate: rebase before every commit, and push early.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-23 | Jesus Lara / Claude | Initial draft — loader-backed acquisition, file/folder/URL sources, document metadata to manifest columns + page frontmatter |
| 0.2 | 2026-08-23 | Jesus Lara / Claude | Approved. Folded three §8 resolutions into the design: `.md` frontmatter parsed-and-stripped (`split_frontmatter`), triage provenance emitted under a nested `triage:` key (`TriageProvenance`), identical frontmatter across a source's pages |
