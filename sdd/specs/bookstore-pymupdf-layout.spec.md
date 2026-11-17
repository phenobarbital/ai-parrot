---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [bookstore, pageindex, pdf, layout]
docs:
  policy: none
---

# Feature Specification: Optional PyMuPDF Layout for Bookstore PDF Ingestion

**Feature ID**: FEAT-875
**Date**: 2026-11-10
**Author**: Jesus Lara / Codex
**Status**: superseded
**Target version**: next feature release (unassigned)

## 1. Motivation & Business Requirements

### Problem Statement

Running `bookstore add` emits a PyMuPDF suggestion to install `pymupdf_layout` for improved page layout analysis. Bookstore currently extracts PDF Markdown with PyMuPDF4LLM and a custom heading detector. The user requested actual Layout integration, then requested an SDD feature specification based on `artifacts/plan_bookstore_pymupdf_layout.md`.

The current workspace pins PyMuPDF 1.27.1 and PyMuPDF4LLM 0.0.27 in the agents extra. No Layout dependency is declared. Simply installing or importing Layout can change extraction semantics and undermine chapter detection, citation page alignment, or concurrent imports. This feature introduces an explicitly selected, tested Layout extraction path.

### Goals

- Offer optional PyMuPDF Layout analysis for PDF ingestion through Bookstore and PageIndex.
- Preserve the default extractor and existing custom heading behavior.
- Keep every physical page represented, with correct citation and segment ownership.
- Preserve Bookstore failure atomicity and existing re-indexing semantics.
- Establish a reproducible compatible dependency set and real-PDF comparison evidence before release.

### Non-Goals (explicitly out of scope)

- Making Layout the default, suppressing the suggestion without integrating Layout, or automatic fallback after Layout failures.
- OCR, scanned/image-only PDF support, a general PyMuPDF 2.x migration, or changes to unrelated document loaders.
- Replacing Bookstore's structure selection, optimizer, catalog schema, or LLM adapter.
- Automatic re-indexing of the existing library or new Bookstore MCP write tools.

## Governing Decisions

<!-- decision-audit: input_digest=sha256:57cbecc36d3fd876a0113f0cc09163ed39abe6d95f7ba005584ca2972816cb59 evaluation_digest=sha256:b3237790f030a42c5257a704c34281b27bdbc55a4ef5e2174591507bf42da7ef rules_version=1 status=pass -->

No eligible decisions govern subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools

## 2. Architectural Design

### Overview

Add `pdf_backend="legacy" | "pymupdf-layout"`, default `legacy`. Expose it as `--pdf-backend` on `bookstore add` and `bookstore add-folder`, as a keyword on `Bookstore.add_book` / `add_folder` and `PageIndexToolkit.import_pdf`, and as a recognized `build_page_index(options=...)` key. Backend names are intentionally distinct from `structure_mode="auto" | "layout" | "llm"`.

The legacy path continues to call `extract_markdown_per_page(..., hdr_info=LayoutHeaders(profile))`. The new backend explicitly uses PyMuPDF Layout's native heading classification; it must not claim to invoke `LayoutHeaders` or silently ignore a supplied callback. Both paths still use `analyze_layout` for bookmark and document signals, then the existing segmentation, confidence scoring, bookmark/hybrid selection, optimizer, and publication path. Layout-native headings may differ; the quality gate below determines whether this backend is shippable. If they fail the gate, stop for a design revision rather than removing assertions or inventing a heading reconciliation algorithm in a task.

Run Layout extraction in a fresh subprocess, activated only for an explicitly requested Layout import. Never toggle PyMuPDF's global Layout state in the main server process. This isolates native initialization, import-order behavior, diagnostics, and simultaneous legacy imports. Use `asyncio.create_subprocess_exec` with the current interpreter and an argument vector, no shell, and absolute PDF/output paths. Communicate one Pydantic request/result as UTF-8 JSON over stdin/stdout. Redirect vendor diagnostic stdout to stderr inside the child before importing Layout; JSON is the sole stdout protocol. The parent drains both pipes asynchronously. A 300-second extraction timeout terminates and reaps the child; cancellation also reaps it and propagates cancellation. A nonzero exit, malformed result, timeout, or missing package raises `PDFStructureError` with a bounded diagnostic. There is no retry through the legacy backend.

The first implementation gate establishes a compatible **pre-automatic-Layout** dependency family. Upstream documents Layout support beginning at 0.2.0, page-chunk fixes at 0.2.7, and automatic Layout installation/activation in 1.27.2.1. Investigate 0.2.9 first, with PyMuPDF 1.27.1 where supported; these are candidates, not verified compatible pins. Do not update to the latest release. If no compatible optional family passes the required tests and workspace resolution, revise this draft before implementation proceeds beyond M1. [Upstream change log](https://github.com/pymupdf/pymupdf4llm/blob/main/CHANGES.md).

### User-visible behavior

```text
bookstore add manual.pdf --pdf-backend pymupdf-layout --no-llm
bookstore add manual.pdf --pdf-backend pymupdf-layout --force --no-llm
bookstore add-folder ./books --pdf-backend pymupdf-layout --no-llm
```

- Omission selects legacy, regardless of whether Layout is installed. `--no-llm` still allows local Layout inference and suppresses remote model calls.
- Mixed folders apply the option to PDFs only; non-PDF behavior is unchanged. `--dry-run` does not initialize Layout or spawn a child.
- Unknown names fail before ingestion. Explicit Layout with missing or incompatible dependencies fails with an install hint for `ai-parrot[bookstore-layout]`.
- Existing source SHA deduplication remains: selecting a different backend alone does not re-index an unchanged book. Use `--force`; help and documentation must explain this. Failures must not replace the previously published card, tree, or citation data.
- Path-based PDFs are supported. Explicit Layout for a `BytesIO` input raises `ValueError` before PDF processing; legacy stream behavior stays unchanged.
- Image-only PDFs retain `NoTextLayerError`. Disable automatic OCR in the selected backend using its verified API; M1 must demonstrate this rather than assume a keyword exists.
- Backend and package versions are logged to the existing logger, without adding catalog fields or altering `structure_source` semantics.

### Component Diagram

```text
Bookstore add / add-folder
    -> Bookstore.add_book(pdf_backend)
    -> PageIndexToolkit.import_pdf(pdf_backend)
    -> build_page_index(options) -> _layout_pages(pdf_backend)
         -> analyze_layout (existing document/bookmark signals)
         -> legacy: extract_markdown_per_page + LayoutHeaders
         -> pymupdf-layout: await extract_layout_pages -> isolated worker
         -> segment_pages -> existing structure selection -> existing publication
```

### Integration Points

| Existing component | Integration | Contract |
|---|---|---|
| Bookstore CLI and manager | additive option forwarding | Both folder loops forward the option, defaults preserved |
| `ConfigLoader` | new recognized option | Add `pdf_backend: legacy` to defaults; reject unknown values in builder |
| `PageIndexToolkit.import_pdf` | additive keyword | Include backend in builder options; retain exception propagation |
| `_layout_pages` | explicit dispatch | Await the new backend only for Layout; legacy still receives `LayoutHeaders` |
| `PDFStructureError` | reuse | Backend execution failures become existing Bookstore-friendly errors |
| `extract_markdown_per_page` | unchanged reference contract | Dense 1-based physical-page Markdown; optional image API stays legacy |

### Data Models

New internal transport models in `pdf_layout_backend.py` (not catalog schemas):

```python
class LayoutExtractionRequest(BaseModel):
    """Absolute local PDF path for an isolated, OCR-disabled extraction."""
    pdf_path: str

class LayoutExtractionResult(BaseModel):
    """Validated physical-page Markdown and installed extraction package versions."""
    pages: list[tuple[int, str]]
    page_count: int
    versions: dict[str, str]
```

Require `page_count >= 1`, exactly that many pages, and consecutive IDs 1 through N. Validate vendor page identities, not just list length: missing, duplicate, reordered, or out-of-range pages fail closed. Blank physical pages appear as empty strings. Reconstruct a missing blank page only if the API exposes unambiguous physical identities and independently verifies that page is blank; otherwise fail. No filesystem paths to source PDFs are interpolated into executable code.

### New Public Interfaces

The externally visible change is the additive `pdf_backend` keyword/CLI flag. The new extraction module is an internal PageIndex adapter, not a new LLM tool. See exact skeletons in §3.

## 3. Module Breakdown

### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 dependency compatibility | no | Optional `bookstore-layout` extra, compatible bounded versions, isolated evidence | Actual version tuple and native heading quality need experiments |
| M2 isolated extraction | no, until M1 | JSON models, async subprocess, error contract and page validation below | Vendor activation, OCR-disable and page metadata APIs require M1 evidence |
| M3 PageIndex routing | yes after M1 | Default `legacy`, options validation, explicit dispatch, same downstream structure | — |
| M4 Bookstore wiring | yes | Additive keyword, click choice, both folder loops, unchanged SHA dedupe | — |
| M5 integration and documentation | yes after M1 | Acceptance matrix and documentation paths fixed below | — |

### Module 1: Compatible optional dependencies

- **Paths**: `packages/ai-parrot/pyproject.toml`, generated `uv.lock`; create `sdd/state/FEAT-875/layout-compatibility.md`.
- **Responsibility**: Verify the version family in an isolated environment, record package metadata and platform/Python constraints, activation API, OCR disabling, page identities, native heading quality, and legacy behavior with Layout installed/absent. Add the optional extra only after the result is known and dependency addition is authorized. Reconcile the existing agents pins; extras cannot solve contradictory pins in a shared uv workspace.
- **Depends on**: none. This is a design/compatibility gate, not a mechanical package installation.
- **Interface Skeleton**: Packaging-only interface: `ai-parrot[bookstore-layout]` includes the existing Bookstore requirements plus a tested optional Layout dependency. Existing `ai-parrot[bookstore]` must not acquire Layout transitively. No Python API added.
- **Exit evidence**: Exact resolved versions, wheel/platform availability, recorded license metadata, smoke commands/results and compatibility conclusions in the Markdown report. Test logs live under `artifacts/logs/`; do not commit large environments or PDF copies. If core version upgrades break unrelated loader contracts, stop and revise scope instead of expanding it silently.

### Module 2: Isolated Layout adapter

- **Paths**: create `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_layout_backend.py` and `packages/ai-parrot/tests/knowledge/pageindex/test_pdf_layout_backend.py`.
- **Depends on**: M1's verified vendor API and version tuple.
- **Responsibility**: Transport models above; dependency/activation checks; deterministic page contract; subprocess lifecycle; bounded diagnostics; real native extraction tests. No new image extraction API: the worker disables image file writes and emits text/Markdown only.
- **Interface Skeleton**:

```python
# New module. PDFStructureError verified: packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py:51
async def extract_layout_pages(pdf_path: str | Path, *, timeout_s: float = 300.0) -> list[tuple[int, str]]:
    """Extract dense physical pages in an isolated child; raise PDFStructureError on failure.

    Require a positive timeout. Terminate and reap on timeout/cancellation; cancellation propagates.
    """

def extract_layout_document(request: LayoutExtractionRequest) -> LayoutExtractionResult:
    """Child-only native extraction, with OCR and image writes disabled and page IDs validated."""

def main() -> int:
    """Consume one JSON request, emit one result, and return zero; diagnostics use stderr."""
```

The child entry point is `python -m parrot.knowledge.pageindex.pdf_layout_backend`. It must safely initialize under the package's real import graph, including imports of PageIndex's `__init__`; M1 verifies the ordering rather than assuming a pristine namespace. Do not send callbacks or PyMuPDF document objects across the boundary. Parent and worker both validate result shape. Test cancellation, startup failure, invalid JSON, invalid page IDs, and vendor noise without invoking an LLM.

### Module 3: PageIndex option and routing

- **Paths**: `packages/ai-parrot/src/parrot/knowledge/pageindex/{utils.py,builder.py,toolkit.py}`.
- **Depends on**: M2 for `extract_layout_pages`; M1 for a supported dependency set.
- **Interface Skeleton**:

```python
# Existing signature preserved; new options key only.
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py:1571
async def build_page_index(
    doc: str | BytesIO,
    adapter: Optional[PageIndexLLMAdapter] = None,
    options: dict | config | None = None,
    light_adapter: Optional[PageIndexLLMAdapter] = None,
    llm_concurrency: int = DEFAULT_LLM_CONCURRENCY,
) -> dict:
    """Validate pdf_backend and route path extraction; preserve structure_mode semantics."""

# Modified private signature; verified: packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py:1683
async def _layout_pages(
    doc: str, *, pdf_backend: str = "legacy"
) -> tuple[LayoutProfile, list[tuple[int, str]], list[Segment]]:
    """Dispatch extraction while retaining existing analysis and segmentation contracts."""

# Existing class/method; verified: packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:2150
async def import_pdf(
    self,
    tree_name: str,
    pdf_path: str,
    parent_node_id: Optional[str] = None,
    with_summaries: bool = True,
    with_doc_description: bool = False,
    doc_id: Optional[str] = None,
    structure_mode: str = "auto",
    *,
    pdf_backend: str = "legacy",
) -> dict[str, Any]:
    """Import using the selected extractor without changing publication or structure selection."""
```

`ConfigLoader._DEFAULTS` gains `"pdf_backend": "legacy"` (verified `utils.py:776`). The existing `load(self, user_opt: dict | config | None = None) -> config` signature is unchanged. No import or inference of Layout on legacy requests. Do not pass `hdr_info` to the new adapter; this explicitly selects native headings.

### Module 4: Bookstore API and CLI

- **Paths**: `packages/ai-parrot/src/parrot/knowledge/bookstore/{library.py,cli.py}`.
- **Depends on**: M3's `import_pdf` keyword.
- **Interface Skeleton**:

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1426
async def add_book(
    self, file_path: str | Path, scope: str = "project", title: Optional[str] = None,
    authors: Optional[list[str]] = None, topics: Optional[list[str]] = None,
    force: bool = False, *, relate: bool = False, pdf_backend: str = "legacy",
) -> tuple[BookCard, str]:
    """Forward PDF backend; keep source identity, staging, force and rollback behavior."""

# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1814
async def add_folder(
    self, folder: str | Path, scope: str = "project", recursive: bool = False,
    force: bool = False, *, relate: bool = False, pdf_backend: str = "legacy",
) -> dict[str, Any]:
    """Forward the PDF option per file; preserve mixed-format and per-file failure behavior."""

# Click callbacks verified: packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:117,176
# Add the trailing argument to both callbacks; existing arguments remain in order.
def add(
    file: str, global_scope: bool, title: Optional[str], authors: tuple[str, ...],
    topics: tuple[str, ...], force: bool, no_llm: bool, relate: bool,
    llm: Optional[str], pdf_backend: str = "legacy",
) -> None:
    """Index FILE with an explicit PDF extractor; changing extractors requires --force."""

def add_folder(
    folder: str, recursive: bool, global_scope: bool, force: bool, no_llm: bool,
    relate: bool, llm: Optional[str], dry_run: bool, pdf_backend: str = "legacy",
) -> None:
    """Index a folder; forward the PDF option in this callback's independent loop."""
```

Use Click's `Choice(["legacy", "pymupdf-layout"])`, default `legacy`, on both commands. Public Python entry points also reject unknown names. Non-PDF inputs ignore either valid backend. Preserve `BookstoreError` conversion for PDF failures. A dependency preflight must not bypass the existing SHA-skip semantics or initialize inference during dry runs.

### Module 5: Regression coverage and documentation

- **Paths**: create `packages/ai-parrot/tests/knowledge/pageindex/test_pdf_backend_integration.py`, `packages/ai-parrot/tests/knowledge/bookstore/test_pdf_backend.py`, and `wiki/knowledge/bookstore-pymupdf-layout.md`; update `wiki/knowledge/pageindex-layout-structure.md`.
- **Depends on**: M2, M3, M4; M1 report supplies version-specific assertions and installation instructions.
- **Interface Skeleton**: Test-only and documentation module; no production API. New test entry points:

```python
async def test_layout_import_preserves_physical_pages(tmp_path: Path) -> None:
    """Native Layout preserves page citations, blank pages and segment ownership."""

async def test_layout_failure_preserves_published_book(tmp_path: Path) -> None:
    """An explicit backend failure leaves the prior publication readable."""

def test_cli_pdf_backend_forwarding() -> None:
    """Both add commands pass the choice; dry-run does not initialize extraction."""
```

## 4. Test Specification

### Unit Tests

| Test case | Module | Required assertion |
|---|---|---|
| Request/result validation | M2 | Malformed paths/results, duplicate/reordered pages and bad IDs rejected |
| Worker lifecycle | M2 | Startup errors, timeout, cancellation and native failures reap child; diagnostic is bounded |
| Protocol purity | M2 | Vendor stdout cannot corrupt JSON or parent MCP stdout |
| Backend options | M3/M4 | Default legacy; invalid values fail early; explicit Layout streams rejected |
| CLI forwarding | M4/M5 | `add`, CLI `add-folder`, and manager `add_folder` all forward |
| Missing dependency | M2/M5 | Actionable error, no implicit downgrade; legacy still usable |
| Force/dry-run | M4/M5 | Unchanged-source skip, explicit force regeneration, no dry-run worker |

### Integration Tests

| Scenario | Required evidence |
|---|---|
| Real Layout extraction | Installed supported Layout runs on a generated multi-column PDF; column sentinel order is correct and body tokens are not dropped/duplicated |
| Tables | Generated ruled table preserves all labeled cell values in row order |
| Headings | Generated chapter/subsection fixtures retain every expected heading and page; body-sized bold and enumerated-title examples are included |
| Bookmarks and no-LLM | Bookmark and hybrid trees still cite valid pages; `--no-llm` invokes no remote model |
| Physical pages | PDF with a blank middle page returns every physical page with correct sentinels |
| Atomicity | Failure during a forced Layout re-index preserves published card/tree/retrieval; no new public book on initial failure |
| Isolation | Concurrent legacy and Layout requests cannot affect one another's heading mode or import state |
| Legacy regressions | Existing extraction, layout structure, image extraction and Bookstore suites pass with optional package both absent and present |
| Real corpus | Existing arxiv PDF compared against baseline; page alignment and text retention are mandatory; record heading/table differences without claiming universal improvement |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/pageindex/test_pdf_layout_backend.py
- packages/ai-parrot/tests/knowledge/pageindex/test_pdf_backend_integration.py
- packages/ai-parrot/tests/knowledge/pageindex/test_pdf_to_markdown.py
- packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py
- packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py
- packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py
- packages/ai-parrot/tests/knowledge/bookstore/test_pdf_backend.py
- packages/ai-parrot/tests/knowledge/bookstore/test_cli.py
- packages/ai-parrot/tests/knowledge/bookstore/test_library.py
- packages/ai-parrot/tests/sdd/test_techwiki_check.py
markers: none

### Validation Requirements

New test paths are declared deliverables, not existing files. Native tests may skip only in the base installation job; feature validation requires a Layout-enabled job with zero native-test skips plus a base-install job proving optionality. No network/LLM calls in deterministic tests. Collect cold and warm extraction duration and peak child memory for both backends; report measurements without inventing an unsupported performance target. Logs belong in `artifacts/logs/`.

### Test Data / Fixtures

Generate small PDFs in pytest temporary directories: two columns with unique sentinels, table rows with unique cell labels, bookmarks, bold/enumerated headings, blank middle page, and unreadable/image-only input. Reuse `packages/ai-parrot/tests/knowledge/pageindex/fixtures/arxiv_2408_09869.pdf` read-only. Larger private library PDFs can inform optional comparisons but are never required CI inputs or committed artifacts.

## 5. Acceptance Criteria

- [ ] M1 records a verified dependency tuple; the optional extra resolves with existing workspace extras and does not activate Layout on default imports.
- [ ] Both CLI commands and Python entry points accept the explicit backend choice, with legacy as default.
- [ ] Layout runs in an isolated process without blocking the event loop; cancellation and timeouts leave no worker alive.
- [ ] Layout output preserves physical-page identity, blank pages, segment ownership and citation alignment.
- [ ] Native two-column, table and heading fixtures meet §4's content/order assertions; native heading limitations are documented.
- [ ] Legacy custom heading behavior and image extraction remain covered and passing with Layout installed and absent.
- [ ] Missing/incompatible Layout, invalid output and native failures produce actionable errors without silent fallback or corrupt publication.
- [ ] `--no-llm`, mixed folders, dry-run and SHA/force semantics remain correct.
- [ ] Base-install and Layout-enabled validation jobs pass; the enabled job actually executes native tests.
- [ ] Comparison report records versions, text/heading/table outcomes, extraction time and memory.
- [ ] Wiki documentation explains installation, native versus custom headings, re-indexing and troubleshooting.

## 6. Codebase Contract

Verified against base commit `38ff4b6d5ae2e08015dee481d96674b106205a31`. Wiki symbol line numbers were stale for `import_pdf`; the source was re-read and the current anchor is line 2150.

### Verified Imports

Source-backed import contracts (not a claim of executing every import during specification):

```python
from parrot.knowledge.pageindex.pdf_to_markdown import extract_markdown_per_page
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py:40
from parrot.knowledge.pageindex.layout import LayoutHeaders, LayoutProfile, PDFStructureError
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py:598,94,51
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
# verified caller: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:35
```

### Existing Class Signatures

- `ConfigLoader.load(self, user_opt: dict | config | None = None) -> config`: `packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py:805`; `_validate_keys` rejects options absent from defaults.
- `LayoutHeaders.__init__(self, profile: LayoutProfile) -> None` and `get_header_id(self, span: dict, page: Any = None) -> str`: `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py:603,623`.
- `extract_markdown_per_page(pdf_path: str | Path, *, images_dir: str | Path | None = None, image_format: str = "png", dpi: int = 150, image_size_limit: float = 0.05, hdr_info: Any = None) -> list[tuple[int, str]]`: `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py:40`.
- Existing manager and toolkit signatures appear in §3 with only the proposed additive keyword; all pre-existing parameters are preserved.

### Integration Points

| New component | Existing connection | Verified at |
|---|---|---|
| CLI option | `store.add_book` in single-file command | `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:143` |
| Folder CLI option | Independent `store.add_book` loop, not `store.add_folder` | `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:225` |
| Manager folder option | `self.add_book` loop | `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1856` |
| Manager PDF option | `toolkit.import_pdf` and `PDFStructureError` conversion | `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1504` |
| Toolkit option | `build_page_index(options=...)` | `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:2181` |
| Builder dispatch | `_layout_pages`, analysis/extraction/segmentation | `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py:1683` |

### Does NOT Exist (Anti-Hallucination)

- No `pageindex/config.py`; configuration is `ConfigLoader` in `utils.py`.
- No existing `pdf_backend` option, `pdf_layout_backend.py`, `bookstore-layout` extra, or declared `pymupdf-layout` dependency in the inspected integration surface.
- Existing `structure_mode="layout"` means local tree structure selection, not PyMuPDF Layout activation.
- Distribution name `pymupdf-layout` is not proof of an import called `pymupdf_layout`. M1 must verify the actual activation import for the chosen release.
- Do not assume Layout honors `hdr_info`, exposes a stable page-box schema, or accepts legacy image/OCR flags.

### Edit Sites (Blueprint Anchors)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | `bookstore = [` | `packages/ai-parrot/pyproject.toml:382` | 1 |
| `uv.lock` | MODIFY | `name = "pymupdf4llm"` | `uv.lock:12891` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py` | MODIFY | `class ConfigLoader:` | `packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py:773` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py` | MODIFY | `async def _layout_pages(doc: str) -> tuple[LayoutProfile, list[tuple[int, str]], list[Segment]]:` | `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py:1683` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `async def import_pdf(` | `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:2150` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `async def add_book(` | `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1426` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `@bookstore.command("add")` | `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:103` | 1 |
| `wiki/knowledge/pageindex-layout-structure.md` | MODIFY | `## How structure is chosen` | `wiki/knowledge/pageindex-layout-structure.md:21` | 1 |
| `sdd/state/FEAT-875/layout-compatibility.md` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_layout_backend.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/pageindex/test_pdf_layout_backend.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/pageindex/test_pdf_backend_integration.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/bookstore/test_pdf_backend.py` | CREATE | — | — | — |
| `wiki/knowledge/bookstore-pymupdf-layout.md` | CREATE | — | — | — |

`uv.lock` is generated with uv, never edited by hand. M1 also reconciles the agents pins at `packages/ai-parrot/pyproject.toml:490-491`. Existing test files in the validation contract are regression operands; only the new test files above are planned edits. The legacy extractor and `layout.py` are reference contracts, not modification targets.

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Use Pydantic v2 for transport validation, async subprocess I/O, existing loggers, and the existing `PDFStructureError` chain. No new provider SDK calls or LLM adapter changes.
- Keep existing positional arguments intact; add keywords at the end. No implicit backend based on import availability.
- Keep CPU/native Layout work in the child, not an event-loop callback or newly introduced thread. Do not refactor unrelated pre-existing worker-thread calls.
- The normal segment store/revision pipeline remains authoritative. Never publish an unvalidated Layout result, renumber physical pages by enumeration after dropping blanks, or mix text from one backend with another's segment offsets.
- Use a feature worktree for implementation. Package experiments must not mutate a shared environment. Do not install packages while authoring this specification.

### Known Risks / Gotchas

| Risk | Required mitigation |
|---|---|
| Optional extra conflicts with agents pins | M1 resolves a single compatible tuple across extras; cannot just add a conflicting minimum |
| Newer PyMuPDF4LLM auto-activates Layout | Select and verify an optional release family; no unconditional latest-version upgrade |
| Native headings differ from `LayoutHeaders` | Explicitly documented backend behavior and strict fixture gate; no silent callback dropping |
| Importing a worker module loads PageIndex first | Verify actual import graph and activation sequence in M1; worker-only configuration must still activate the native engine |
| Vendor chunk/output schema changes | Normalize against a verified version and validate physical page IDs before returning |
| OCR implicitly activates on mixed pages | Explicitly disable it with a verified API; scanned-PDF behavior remains unchanged |
| Large child response or diagnostics | Drain pipes concurrently, truncate reported diagnostics, collect representative memory measurements |
| Backend change on unchanged source is skipped | Preserve SHA identity and document `--force`; do not silently change deduplication |
| Process inference overhead | Measure cold/warm time and memory; process pooling is outside this feature |
| Native dependencies unavailable on a platform | Base Bookstore remains installable; document supported optional platforms accurately |

### External Dependencies

| Package | Existing / proposed version | Reason |
|---|---|---|
| `pymupdf` | Existing 1.27.1; candidate retained pending M1 | PDF reading and Layout integration |
| `pymupdf4llm` | Existing 0.0.27; candidate 0.2.9 pending M1 | Layout-aware Markdown with physical page chunks |
| `pymupdf-layout` | New optional dependency; exact compatible version unresolved | Native layout classification |
| Transitive inference dependencies | Resolve from the selected release metadata | Do not add unrelated inference libraries manually |

The candidate version is a research starting point, not a claimed compatibility result. Dependency addition remains subject to the repository's dependency-hygiene approval; this spec request authorizes planning, not environment installation. Confirm package licensing and supported platforms from the selected distribution metadata as part of dependency review.

## Consequences

<!-- decision-audit: input_digest=sha256:57cbecc36d3fd876a0113f0cc09163ed39abe6d95f7ba005584ca2972816cb59 evaluation_digest=sha256:b3237790f030a42c5257a704c34281b27bdbc55a4ef5e2174591507bf42da7ef rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/bookstore-pymupdf-layout.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: layout, pdf
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "layout",
      "pdf"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/bookstore-pymupdf-layout.spec.md"
    }
  ],
  "evaluation_digest": "sha256:b3237790f030a42c5257a704c34281b27bdbc55a4ef5e2174591507bf42da7ef",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:57cbecc36d3fd876a0113f0cc09163ed39abe6d95f7ba005584ca2972816cb59",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {},
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Scope: use the prior implementation plan to produce an SDD feature specification — user request, 2026-11-10.
- [x] Rollout: optional backend with existing behavior as default — carried forward from the implementation plan.
- [x] Structure versus extraction: separate `pdf_backend` from existing `structure_mode` — source-verified design decision in this draft.
- [x] Heading semantics: legacy uses custom `LayoutHeaders`; explicitly selected Layout uses native headings and must pass the quality gate. No promise of identical chapter trees across backends.
- [x] Re-indexing: require existing `--force` for unchanged source bytes when switching extractors; no catalog migration.
- [ ] Confirm the exact compatible package tuple, activation/OCR/page-identity API and native heading fixture results — owner: M1 implementation/design owner; prerequisite to M2 and final spec approval.
- [ ] Approve the missing dependency addition and resulting pin changes after reviewing M1's evidence — owner: repository maintainer. No package installation is performed by this specification workflow.
- [ ] Assign a release version — owner: maintainer; not a blocker to reviewing this draft.

## 9. Design Research Cross-Check

Status: skipped (input is the user-selected implementation plan/direct notes, not an accepted brainstorm/proposal or a completed intake session; the optional independent-research precondition is not met).

Codebase contracts were verified directly. No independent review is claimed.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

## 10. Documentation

- **Policy**: required.
- Update `wiki/knowledge/pageindex-layout-structure.md`: distinguish structure mode from extraction backend, explain native/custom heading differences and replace the outdated implication that the Layout suggestion can only be ignored.
- Create `wiki/knowledge/bookstore-pymupdf-layout.md`: supported dependency tuple/platforms, uv installation instructions, CLI/Python examples, no-LLM behavior, mixed folders, dry-run, `--force`, missing-package/timeout errors, rollback guarantees and comparison results.
- API modules: `parrot.knowledge.pageindex.pdf_to_markdown` remains the legacy reference; `parrot.knowledge.pageindex.pdf_layout_backend` documents the new transport, errors and lifecycle. Modified CLI/manager/toolkit docstrings document the option.
- Document limits honestly: native inference can change headings and extraction quality is corpus-dependent; retaining the legacy backend is intentional.

## Worktree Strategy

- **Isolation**: per-spec — one feature worktree for FEAT-875; task sub-worktrees follow normal SDD tooling.
- **Dependency graph**: M2 → M1 (verified vendor API), M3 → M2 (async extraction API), M4 → M3 (toolkit option), M5 → M2/M3/M4 (complete ingestion path). Contract-only CLI work may be scheduled independently once M3's interface is frozen; do not invent extra dependency edges merely to serialize work.
- **Shared files**: M3 owns PageIndex option/routing files; M4 owns both Bookstore files; M5 owns new integration tests and docs. No overlapping file ownership is planned.
- **Exclusive resources**: M1 lockfile resolution and any environment mutation use `parallel: false`; isolate native tests/installation jobs from the shared primary environment.
- **Cross-feature dependencies**: existing PageIndex layout/segment-store and Bookstore atomic re-indexing code are already on the verified base. No unmerged feature dependency identified.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-10 | Jesus Lara / Codex | Draft from implementation plan; verified contracts, optional backend, compatibility and quality gates |
| 0.2 | 2026-11-10 | Jesus Lara / Claude | **Superseded.** M1 (`sdd/state/FEAT-875/layout-compatibility.md`) found `pymupdf-layout` is Polyform Noncommercial, native headings are flat (hierarchy lost) versus the legacy extractor, and the extra conflicts with the `agents` pins. Decision: do not adopt `pymupdf.layout`; improve the current extractor instead. Only a tolerant `pymupdf`/`fitz` import (`pageindex/_pymupdf.py`) landed under this feature. Tasks TASK-5470..5474 were removed. |
