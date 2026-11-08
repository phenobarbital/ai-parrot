# TASK-5340: Builder orchestration (M5)

**Feature**: FEAT-845 — PageIndex Layout Structure Builder
**Spec**: `sdd/specs/pageindex-layout-structure.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5334, TASK-5335, TASK-5337, TASK-5339
**Assigned-to**: unassigned

---

## Context

Spec §2 "Pipeline" (steps 1–6), the rev 0.2 failure paragraph, "No adapter", "Mode scope",
"Configuration", and §3 Module 5. This task rewires `build_page_index` into the layout-first pipeline:

1. `get_page_tokens` in a worker thread → `UnreadablePDFError` / `NoTextLayerError`;
2. `analyze_layout` (TASK-5333) → 3. layout-aware extraction with `hdr_info=LayoutHeaders(profile)`
   (TASK-5334, TASK-5335) and `segment_pages`, each in a worker thread, with **explicit** failure
   (`PDFStructureError` naming the stage, cause chained; empty content also raises — rev 0.2, AC-19);
4. `build_structure` (TASK-5337) → 5. the LLM pipeline (`tree_parser`, prompts framed by TASK-5339) in
   `auto`/`llm` mode with an adapter, else / on LLM failure one node per page;
6. node ids, `structure_source` on every node, optional summaries/description (skipped with no adapter),
   one return dict with `structure_source`, `structure_report`, `_pages`, `_segments`, `_node_markdown`.

It also adds the two option keys, the `PageIndexNode.structure_source` field and the package exports,
deletes `_extract_node_markdown`, and replaces `test_builder_pages.py`.

---

## Scope

- `builder.py`: add imports; replace `build_page_index` (builder.py:1545-1621 before TASK-5339) with the new
  pipeline (`adapter` becomes optional); add `_STRUCTURE_MODES`, `_doc_label`, `_read_page_tokens`,
  `_layout_stage`, `_layout_pages`, `_candidate_scores`, `_choose_structure`; delete `_extract_node_markdown`
  (builder.py:1624-1640, the module's last function).
- `utils.py`: `ConfigLoader._DEFAULTS` gains `"structure_mode": "auto"` and `"structure_min_confidence": 0.6`.
- `schemas.py`: `PageIndexNode.structure_source: Optional[str] = None`.
- `__init__.py`: export `LayoutProfile`, `NoTextLayerError`, `PDFStructureError`, `StructureReport`,
  `UnreadablePDFError`, `analyze_layout`.
- Create `test_builder_layout.py` (six tests, spec §4 M5 rows); rewrite `test_builder_pages.py` entirely.

**NOT in scope**:
- The 13 structure-prompt functions and their framing (TASK-5339 — already done when you start; do not touch them).
- `generate_node_summary` / `generate_doc_description` prompts (slice 5 — unchanged).
- `import_pdf`, `_segments` reuse, anchor stripping (TASK-5341); `attach_pdf_document` (TASK-5338).
- Changing the default threshold (TASK-5344); Bookstore (TASK-5342).
- Changing `build_structure`'s signature — it is fixed by the spec skeleton.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py` | MODIFY | New `build_page_index` pipeline + helpers; delete `_extract_node_markdown`; imports |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py` | MODIFY | Two `ConfigLoader._DEFAULTS` keys |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py` | MODIFY | `PageIndexNode.structure_source` |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py` | MODIFY | Six exports |
| `packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py` | CREATE | Six M5 behaviour tests |
| `packages/ai-parrot/tests/knowledge/pageindex/test_builder_pages.py` | MODIFY | Full rewrite: return-dict keys, `_layout_pages` propagation, thread offload |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# already in builder.py (verified at HEAD 8dbdb08cbb)
import asyncio                                                      # builder.py:4
from io import BytesIO                                              # builder.py:10
from types import SimpleNamespace as config                         # builder.py:11
from typing import Any, Awaitable, Iterable, Optional               # builder.py:12
from .llm_adapter import PageIndexLLMAdapter                        # builder.py:14
from .pdf_to_markdown import build_node_markdown_map, extract_markdown_per_page   # builder.py:15
from .utils import (ConfigLoader, add_node_text, get_page_tokens, get_pdf_name, remove_structure_text,
                    write_node_id, create_clean_structure_for_description, ...)    # builder.py:24-44
# new in builder.py
from pathlib import Path                                            # stdlib
from .segments import Segment, segment_pages                        # segments.py:33, :231
from .utils import structure_to_list                                # utils.py:294 — add to the existing .utils import list
# tests
import pymupdf                                                      # 1.27.1 — Document, new_page, insert_text, set_toc, draw_rect
from parrot.knowledge.pageindex import builder                      # module under test
```

#### Created by dependencies (must be `done` before you start — re-verify each with `grep -n`)
```python
# TASK-5333 — packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py
from .layout import LayoutProfile, NoTextLayerError, PDFStructureError, UnreadablePDFError, analyze_layout
#   analyze_layout(pdf_path: str) -> LayoutProfile   (sync; raises UnreadablePDFError on open failure)
#   LayoutProfile: page_count, body_size, heading_sizes, running, bold_lines, bookmarks, bookmark_rejection
# TASK-5334 — same file
from .layout import LayoutHeaders                                   # LayoutHeaders(profile).get_header_id(span, page=None)
# TASK-5335 — pdf_to_markdown.py
#   extract_markdown_per_page(pdf_path, *, ..., hdr_info: Any = None)  forwarded to pymupdf4llm only when not None
# TASK-5336 / TASK-5337 — packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py
from .layout_structure import StructureReport, build_structure, page_structure, score_bookmarks, score_layout
#   build_structure(profile, segments, *, mode="auto", min_confidence=0.6) -> Optional[StructureResult]
#   StructureResult: source, structure (nodes with transient "anchor"), report: StructureReport
#   StructureReport(source, mode, min_confidence, confidence=None, candidates=[], inserted_headings=0,
#                   body_size=None, running_lines=0, llm_used=False, llm_error=None)
#   score_bookmarks / score_layout(profile, segments) -> tuple[CandidateScore, list[dict]]
#   page_structure(page_count: int, doc_name: str) -> list[dict]
# TASK-5339 — builder.py gained `from .framing import DATA_FRAMING_INSTRUCTION, frame_text` near line 15
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py (line numbers before TASK-5339; re-grep — they shift)
logger = logging.getLogger("parrot.knowledge.pageindex.builder")    # :46
DEFAULT_LLM_CONCURRENCY = 16                                        # :57
_LLM_SEMAPHORE: contextvars.ContextVar[Optional[asyncio.Semaphore]] # :60
async def tree_parser(page_list, opt, adapter, light_adapter=None) -> list[dict]          # :1436
async def generate_summaries_for_structure(structure, adapter) -> Any                     # :1510
async def generate_doc_description(structure, adapter) -> str                             # :1527
async def build_page_index(doc, adapter, options=None, light_adapter=None,
                           llm_concurrency=DEFAULT_LLM_CONCURRENCY) -> dict              # :1545 (replaced)
    # today :1599-1613: summary branch — add_node_text if text "no", generate_summaries_for_structure(structure, light),
    #   remove_structure_text, and ONLY inside it the description (create_clean_structure_for_description + generate_doc_description)
def _extract_node_markdown(doc, structure) -> tuple[dict[str, str], list[tuple[int, str]]]  # :1624-1640 (deleted; last in file)

# packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py
def get_page_tokens(pdf_path: str | BytesIO, model="gpt-4o", pdf_parser="PyMuPDF") -> list[tuple[str, int]]  # :130
    # str not a file → ValueError("Invalid pdf_path: …") (:162); bad bytes → pymupdf.FileDataError (a RuntimeError) from pymupdf.open (:158 stream, :160 path)
def get_encoder(model="gpt-4o") -> Any | None                       # :37 — may download tiktoken BPE (stub it in tests)
def get_pdf_name(pdf_path: str | BytesIO) -> str                    # :173
def write_node_id(data, node_id=0) -> int                           # :262
def structure_to_list(structure) -> list[dict]                      # :294 — flatten preserving parents
def remove_structure_text(data) -> Any                              # :486
def add_node_text(node, pdf_pages) -> None                          # :500
def create_clean_structure_for_description(structure) -> Any        # :713
class ConfigLoader:                                                 # :761
    _DEFAULTS = {..., "if_add_node_text": "no"}                     # :764-773 (anchor line :772)
    def _validate_keys(self, user_dict) -> None                     # :786 unknown keys → ValueError (validated against the defaults dict)
    def load(self, user_opt=None) -> SimpleNamespace                # :791

# packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py
def extract_markdown_per_page(pdf_path, *, images_dir=None, image_format="png", dpi=150, image_size_limit=0.05) -> list[tuple[int, str]]  # :39
def build_node_markdown_map(structure, pages) -> dict[str, str]     # :211

# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
class Segment(BaseModel): seq; kind; page; ordinal; level; text      # :33
def segment_pages(pages: list[tuple[int, str]]) -> list[Segment]    # :231 — counts tokens via _utils.count_tokens (segments.py:11)

# packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py
class PageIndexNode(BaseModel):                                     # :118
    owned: Optional[list[list[int]]] = None                         # :132 (anchor)
    model_config = {"extra": "allow"}                               # :135

# packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py
from .segment_store import SegmentStore                             # :26 (anchor)
__all__ = [..., "SegmentStore", ]                                   # "SegmentStore", at :54

# packages/ai-parrot/tests/knowledge/pageindex/test_builder_pages.py (replaced entirely)
#   :6 test_extract_node_markdown_returns_pages, :13 test_extract_node_markdown_fallbacks → both call
#   builder._extract_node_markdown (deleted here); :23 test_pages_returned_in_both_branches counts source text.
```

### Does NOT Exist
- ~~`builder._extract_node_markdown`~~ after this task — deleted; nothing else in `packages/` calls it (grep: only the
  test file being rewritten and a stale `build/lib…` copy).
- ~~`import pymupdf` in `builder.py`~~ — the builder never imports pymupdf; catch `RuntimeError` (the base of
  `pymupdf.FileDataError`) around `get_page_tokens`, never `pymupdf.FileDataError`.
- ~~`opt.structure_mode` / `opt.structure_min_confidence`~~ before this task — read them with `getattr(opt, …, default)`.
- ~~`StructureResult.confidence`~~ — confidence is `StructureResult.report.confidence`.
- ~~`build_structure` raising `ValueError` for an unknown mode~~ — this task validates the mode.
- ~~`PageIndexLLMAdapter.model`~~ is not guaranteed — keep the existing `getattr(light_adapter, "model", "?")`.
- ~~a `pymupdf_layout` dependency~~ — not installed, not to be added.
- ~~`conftest.py` under `tests/knowledge/pageindex/`~~ — none exists; fixtures stay in each test module.

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
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_builder_pages.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#build_page_index",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#_extract_node_markdown",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#tree_parser",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#generate_summaries_for_structure",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#generate_doc_description",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py#ConfigLoader",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py#get_page_tokens",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py#get_pdf_name",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py#write_node_id",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py#add_node_text",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py#remove_structure_text",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py#structure_to_list",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py#create_clean_structure_for_description",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py#extract_markdown_per_page",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py#build_node_markdown_map",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#segment_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#Segment",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py#PageIndexNode"
  ]
}
```

---

## Implementation Notes

### Shifted line numbers
TASK-5339 edited `builder.py` first (framing import near line 15 and the 13 prompt functions at 113-1020), so
`build_page_index` and `_extract_node_markdown` have moved by a few lines. Re-grep before editing:
`grep -n 'async def build_page_index(\|def _extract_node_markdown(' packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py`
— each must still occur exactly once. `_extract_node_markdown` must still be the last function in the file.

### Decisions fixed by the feature brief (shared with TASK-5341 / TASK-5345 — do not change)
- **Error messages**: `UnreadablePDFError(f"Cannot open {name}: {exc}")`;
  `NoTextLayerError(f"{name} has no text layer; OCR is not supported")`;
  `PDFStructureError(f"PDF layout {stage} failed for {name}: {exc}")` with `stage` in
  `"analysis" | "extraction" | "segmentation"`, raised `from exc`; empty content:
  `PDFStructureError(f"PDF layout extraction produced no text for {name}")`. `name` is `Path(doc).name` for a path,
  `"PDF stream"` for a `BytesIO` (never call `get_pdf_name` before the PDF opened — it opens the stream).
- `_layout_stage` re-raises an incoming `PDFStructureError` unchanged **before** the generic
  `except (ValueError, ImportError, FileNotFoundError)` (so `UnreadablePDFError` is not re-wrapped).
- **Report when `build_structure` returns `None`**: fill `StructureReport.candidates` with
  `score_bookmarks(profile, segments)[0]` and `score_layout(profile, segments)[0]` (only when `profile is not None`
  and `mode != "llm"`), so AC-4's rejection reason reaches the llm/pages report.
- **Return dict**: exactly `doc_name, structure, structure_source, structure_report (report.model_dump()),
  _node_markdown, _pages, _segments`, plus `doc_description` only when generated. `structure_source` on every node.
- **Mode scope (rev 0.2)**: `structure_mode` controls structure only. With an adapter, `layout` never calls
  `tree_parser`, but summaries and the description follow their options; the description stays **nested inside
  the summary branch** exactly as today. No adapter: summaries/description skipped with `logger.info`.
- **LLM fallback**: `except Exception` (never `BaseException` — cancellation propagates) around `tree_parser` →
  page fallback with `llm_error`. `llm_used = True` whenever `tree_parser` was attempted.
- **BytesIO**: skip `_layout_pages` (no profile, no pages, no segments): LLM pipeline with an adapter in auto/llm,
  else the page fallback over `len(page_list)` pages titled by `get_pdf_name(doc)`.
- Options are read with `getattr(opt, "structure_mode", "auto")` / `getattr(opt, "structure_min_confidence", 0.6)`.
  `ConfigLoader()` is built without a YAML path here, so the new `_DEFAULTS` keys always validate.

### Key Constraints
- AC-16: `get_page_tokens`, `analyze_layout`, `extract_markdown_per_page`, `segment_pages` run through
  `asyncio.to_thread` — nothing new blocks the event loop.
- Keep the `_LLM_SEMAPHORE` set/reset (`try/finally`) and the light-adapter / concurrency `logger.info` lines.
- Tests must stay offline: stub `parrot.knowledge.pageindex.utils.get_encoder` (→ `None`) and
  `parrot.knowledge.pageindex.utils.count_tokens` (→ `max(1, len(t))`).
- Monkeypatched fakes of `extract_markdown_per_page` must accept `**kwargs` — the builder passes `hdr_info=` by keyword
  (spec §7, test_builder_pages.py:7).
- Cross-feature: FEAT-843 and FEAT-844 also edit `__init__.py`; rebase before `/sdd-done`.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py:1545-1640` — the code being replaced.
- `packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py:15-33` — pymupdf PDF-building pattern.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Confirm TASK-5334, -5335, -5337, -5339 are `done` and re-grep the "Created by dependencies" names — *why*: the builder imports all of them.
2. Apply the `utils.py`, `schemas.py` and `__init__.py` blocks — *why*: small, independent, and the builder reads the option keys.
3. Apply builder Block 1 (imports) — *why*: Blocks 2–3 use the new names.
4. Replace `_extract_node_markdown` with builder Block 3 (helpers) — *why*: it is the file's tail; do it before Block 2 so `build_page_index` line numbers stay valid.
5. Replace `build_page_index` with builder Block 2 and complete the FILL INs — *why*: it is the pipeline of spec §2.
6. Write `test_builder_layout.py` and rewrite `test_builder_pages.py` — *why*: spec §4 M5 rows.
7. Run the Validation Commands, then `ruff check` on every touched file — *why*: AC-18; `test_builder_framing.py` guards TASK-5339's work against this rewrite.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py` (MODIFY) — Block 1 of 3: imports
```python
# occurrences: 1 (verified: grep -c 'from io import BytesIO' packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py)
# AFTER — insert below `from io import BytesIO` (verified: builder.py:10)
from pathlib import Path

# occurrences: 1 (verified: grep -c 'from .pdf_to_markdown import build_node_markdown_map, extract_markdown_per_page' builder.py)
# AFTER — insert below that line (verified: builder.py:15; TASK-5339 may have put its framing import next to it — keep both)
from .layout import (
    LayoutHeaders,
    LayoutProfile,
    NoTextLayerError,
    PDFStructureError,
    UnreadablePDFError,
    analyze_layout,
)
from .layout_structure import StructureReport, build_structure, page_structure, score_bookmarks, score_layout
from .segments import Segment, segment_pages

# occurrences: 1 (verified: grep -c '    write_node_id,' builder.py)
# AFTER — insert below `    write_node_id,` inside the `from .utils import (` block (verified: builder.py:42)
    structure_to_list,
```
**Why**: relative imports match the module's style (builder.py:14-44). `structure_to_list` stamps every node.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py` (MODIFY) — Block 2 of 3: `build_page_index`
```python
# occurrences: 1 (verified: grep -c 'async def build_page_index(' builder.py)
# REPLACE — from `async def build_page_index(` through the `        _LLM_SEMAPHORE.reset(sem_token)` line that closes its
#   `finally:` (verified: builder.py:1545-1621 before TASK-5339; re-grep) with:
async def build_page_index(
    doc: str | BytesIO,
    adapter: Optional[PageIndexLLMAdapter] = None,
    options: dict | config | None = None,
    light_adapter: Optional[PageIndexLLMAdapter] = None,
    llm_concurrency: int = DEFAULT_LLM_CONCURRENCY,
) -> dict:
    """Build a PageIndex tree from a PDF: bookmarks or printed headings first, the LLM pipeline as fallback.

    ``structure_mode`` ("auto" | "layout" | "llm") controls structure only; summaries and the description follow
    their own options when an adapter is configured and are skipped without one. ``BytesIO`` input skips layout
    analysis (LLM pipeline with an adapter, else one node per page, no pages).

    Returns:
        ``{doc_name, structure, structure_source, structure_report, _node_markdown, _pages, _segments}`` plus
        ``doc_description`` when generated.

    Raises:
        UnreadablePDFError: PyMuPDF cannot open the document.
        NoTextLayerError: no page carries any text.
        PDFStructureError: layout analysis, extraction or segmentation failed, or produced no text.
        ValueError: unknown ``structure_mode``, or ``structure_mode='llm'`` without an adapter.
    """
    opt = ConfigLoader().load(options)
    mode = getattr(opt, "structure_mode", "auto")
    min_confidence = float(getattr(opt, "structure_min_confidence", 0.6))
    if mode not in _STRUCTURE_MODES:
        raise ValueError(f"Unknown structure_mode {mode!r}; expected one of {sorted(_STRUCTURE_MODES)}")
    if mode == "llm" and adapter is None:
        raise ValueError("structure_mode='llm' needs an LLM adapter")
    page_list = await _read_page_tokens(doc)
    light = light_adapter or adapter
    logger.info("Total pages: %d, Total tokens: %d, structure_mode=%s",
                len(page_list), sum(p[1] for p in page_list), mode)
    if light_adapter is not None and light_adapter is not adapter:
        logger.info("Light adapter active for verify/summaries/title-checks: model=%s",
                    getattr(light_adapter, "model", "?"))
    logger.info("LLM fan-out concurrency cap: %d", llm_concurrency)

    sem_token = _LLM_SEMAPHORE.set(asyncio.Semaphore(max(1, llm_concurrency)))
    try:
        profile: Optional[LayoutProfile] = None
        pages: list[tuple[int, str]] = []
        segments: list[Segment] = []
        if isinstance(doc, str):
            profile, pages, segments = await _layout_pages(doc)
        structure, report = await _choose_structure(
            doc, page_list, profile, segments, mode=mode, min_confidence=min_confidence,
            opt=opt, adapter=adapter, light=light,
        )
        if opt.if_add_node_id == "yes":
            write_node_id(structure)
        for node in structure_to_list(structure):
            node["structure_source"] = report.source
        if opt.if_add_node_text == "yes":
            add_node_text(structure, page_list)
        result: dict[str, Any] = {
            "doc_name": get_pdf_name(doc),
            "structure": structure,
            "structure_source": report.source,
            "structure_report": report.model_dump(),
            "_node_markdown": build_node_markdown_map(structure, pages) if pages else {},
            "_pages": pages,
            "_segments": segments,
        }
        if adapter is None:
            logger.info("No LLM adapter: skipping node summaries and the document description")
        elif opt.if_add_node_summary == "yes":
            # FILL IN: today's summary branch (builder.py:1599-1613 before this change) — add_node_text(structure, page_list)
            #   when if_add_node_text == "no"; await generate_summaries_for_structure(structure, light); remove_structure_text
            #   when if_add_node_text == "no"; then, ONLY here, when if_add_doc_description == "yes":
            #   result["doc_description"] = await generate_doc_description(create_clean_structure_for_description(structure), light)
            #   — bounded by spec §2 "Mode scope" (description nested in the summary branch, as today).
            raise NotImplementedError
        return result
    finally:
        _LLM_SEMAPHORE.reset(sem_token)
```
**Why this shape**: validation happens before any I/O, so `ValueError` for a bad mode never opens the PDF. The
structure is chosen inside the semaphore scope because the LLM fallback fans out. One return dict replaces the two
of today (which `test_builder_pages.py` used to count). `structure_report` is dumped to a plain dict because it is
stored next to the tree by `import_pdf` (TASK-5341).

### `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py` (MODIFY) — Block 3 of 3: helpers
```python
# occurrences: 1 (verified: grep -c 'def _extract_node_markdown(' builder.py)
# REPLACE — delete from `def _extract_node_markdown(` to the END of the file (verified: builder.py:1624-1640 before
#   TASK-5339; it is the last function — its last line is `    return build_node_markdown_map(structure, pages), pages`)
#   and write instead:
_STRUCTURE_MODES = frozenset({"auto", "layout", "llm"})


def _doc_label(doc: str | BytesIO) -> str:
    """File name for a path, a fixed label for a stream (error messages; never opens the PDF)."""
    return Path(doc).name if isinstance(doc, str) else "PDF stream"


async def _read_page_tokens(doc: str | BytesIO) -> list[tuple[str, int]]:
    """Step 1 in a worker thread: UnreadablePDFError on open failure, NoTextLayerError without any text."""
    name = _doc_label(doc)
    try:
        page_list = await asyncio.to_thread(get_page_tokens, doc)
    except (RuntimeError, ValueError) as exc:  # pymupdf.FileDataError is a RuntimeError; a missing path is a ValueError
        raise UnreadablePDFError(f"Cannot open {name}: {exc}") from exc
    if not any(text.strip() for text, _ in page_list):
        raise NoTextLayerError(f"{name} has no text layer; OCR is not supported")
    return page_list


async def _layout_stage(stage: str, name: str, func: Any, *args: Any, **kwargs: Any) -> Any:
    """Run one layout stage in a worker thread; wrap its expected failures as PDFStructureError(stage)."""
    try:
        return await asyncio.to_thread(func, *args, **kwargs)
    except PDFStructureError:
        raise
    except (ValueError, ImportError, FileNotFoundError) as exc:
        raise PDFStructureError(f"PDF layout {stage} failed for {name}: {exc}") from exc


async def _layout_pages(doc: str) -> tuple[LayoutProfile, list[tuple[int, str]], list[Segment]]:
    """analyze_layout + layout-aware extraction + segment_pages, each in asyncio.to_thread;
    raise PDFStructureError with stage and chained cause on ValueError/ImportError/FileNotFoundError,
    or when no non-whitespace segment is produced. Never return empty content as success."""
    name = _doc_label(doc)
    profile = await _layout_stage("analysis", name, analyze_layout, doc)
    pages = await _layout_stage("extraction", name, extract_markdown_per_page, doc, hdr_info=LayoutHeaders(profile))
    segments = await _layout_stage("segmentation", name, segment_pages, pages)
    if not any(seg.text.strip() for seg in segments):
        raise PDFStructureError(f"PDF layout extraction produced no text for {name}")
    logger.info("Layout: body=%s heading_sizes=%s running=%d bookmarks=%d segments=%d", profile.body_size,
                profile.heading_sizes, len(profile.running), len(profile.bookmarks), len(segments))
    return profile, pages, segments


def _candidate_scores(profile: Optional[LayoutProfile], segments: list[Segment], mode: str) -> list:
    """Both deterministic scores for an llm/pages report; empty without a profile or in llm mode."""
    if profile is None or mode == "llm":
        return []
    return [score_bookmarks(profile, segments)[0], score_layout(profile, segments)[0]]


async def _choose_structure(
    doc: str | BytesIO, page_list: list[tuple[str, int]], profile: Optional[LayoutProfile], segments: list[Segment],
    *, mode: str, min_confidence: float, opt: config, adapter: Optional[PageIndexLLMAdapter],
    light: Optional[PageIndexLLMAdapter],
) -> tuple[list[dict], StructureReport]:
    """Steps 4-5: deterministic choice, then the LLM pipeline (auto/llm with an adapter), then one node per page."""
    if profile is not None and mode != "llm":
        chosen = build_structure(profile, segments, mode=mode, min_confidence=min_confidence)
        if chosen is not None:
            return chosen.structure, chosen.report
    report = StructureReport(source="pages", mode=mode, min_confidence=min_confidence,
                             candidates=_candidate_scores(profile, segments, mode),
                             body_size=profile.body_size if profile is not None else None,
                             running_lines=len(profile.running) if profile is not None else 0)
    if adapter is not None and mode in ("auto", "llm"):
        # FILL IN: report.llm_used = True; structure = await tree_parser(page_list, opt, adapter, light_adapter=light);
        #   on success set report.source = "llm" and return (structure, report); on `except Exception as exc` (never
        #   BaseException) logger.warning("LLM structure pipeline failed for %s: %s", ...) and
        #   report.llm_error = str(exc) or type(exc).__name__, then fall through to the page fallback — bounded by
        #   spec §2 Pipeline step 5 and AC-6.
        raise NotImplementedError
    page_count = profile.page_count if profile is not None else len(page_list)
    return page_structure(page_count, get_pdf_name(doc)), report
```
**Why this shape**: `_layout_stage` is the single place the rev 0.2 failure contract lives (stage in the message,
cause chained, `PDFStructureError` re-raised unwrapped), and it looks module globals up at call time so tests can
monkeypatch `builder.analyze_layout` / `builder.extract_markdown_per_page` / `builder.segment_pages`. The page fallback
is reached only for insufficient confidence, `layout` mode, no adapter, or an LLM failure — never for a failed
extraction (that raised already), so it always keeps the extracted pages and segments.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        "if_add_node_text": "no",' packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py)
# AFTER — insert below `        "if_add_node_text": "no",` (verified: utils.py:772)
        "structure_mode": "auto",            # FEAT-845: "auto" | "layout" | "llm"
        "structure_min_confidence": 0.6,     # FEAT-845: provisional; TASK-5344 sets it from the evaluation
```
**Why**: `ConfigLoader._validate_keys` (utils.py:786) rejects unknown option keys, so `import_pdf` cannot pass
`structure_mode` until it is a default key.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    owned: Optional\[list\[list\[int\]\]\] = None' packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py)
# AFTER — insert below `    owned: Optional[list[list[int]]] = None` (verified: schemas.py:132)
    structure_source: Optional[str] = None  # FEAT-845: bookmarks | layout | hybrid | llm | pages (PDF imports only)
```
**Why**: documents the field (the model already allows extras, schemas.py:135); `Optional` is imported at schemas.py:4.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .segment_store import SegmentStore' packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py)
# AFTER — insert below `from .segment_store import SegmentStore` (verified: __init__.py:26)
from .layout import LayoutProfile, NoTextLayerError, PDFStructureError, UnreadablePDFError, analyze_layout
from .layout_structure import StructureReport

# occurrences: 1 (verified: grep -c '    "SegmentStore",' __init__.py)
# AFTER — insert below `    "SegmentStore",` (verified: __init__.py:54)
    "LayoutProfile",
    "NoTextLayerError",
    "PDFStructureError",
    "StructureReport",
    "UnreadablePDFError",
    "analyze_layout",
```
**Why**: spec §3 Module 5 export list. They come after `.builder` is imported (__init__.py:11), which already
imports both modules, so no new import cycle.

### `packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py` (CREATE)
```python
"""FEAT-845 M5 — build_page_index layout-first pipeline, fallbacks and errors."""
from __future__ import annotations

from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from parrot.knowledge.pageindex import builder  # noqa: E402
from parrot.knowledge.pageindex.layout import NoTextLayerError, PDFStructureError  # noqa: E402
from parrot.knowledge.pageindex.utils import structure_to_list  # noqa: E402

BODY = "Body text that fills the page with ordinary sentences about the manual and its many topics."


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.get_encoder", lambda model="gpt-4o": None)
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", lambda t, model="gpt-4o": max(1, len(t)))


def _pdf(path: Path, pages: list[list[tuple[float, str, float, str]]], toc=None) -> Path:
    """pages: per page a list of (y, text, fontsize, fontname); fontname "helv" or "hebo" (bold)."""
    doc = pymupdf.open()
    try:
        for lines in pages:
            page = doc.new_page()
            for y, text, size, font in lines:
                page.insert_text((72, y), text, fontsize=size, fontname=font)
        if toc:
            doc.set_toc(toc)
        doc.save(str(path))
    finally:
        doc.close()
    return path


@pytest.fixture
def headed_pdf(tmp_path) -> Path:
    """4 pages, body 10 pt, headings 16/12 pt bold, running header 'ACME Manual' and page-number footer."""
    # FILL IN: per page n: (30, "ACME Manual", 9, "helv"); heading lines (100, f"Chapter {n}", 16, "hebo") on pages 1 and 3,
    #   (140, f"Section {n}.1", 12, "hebo") on every page; ~20 BODY lines at y = 180 + 18*i, 10 pt "helv" (headings stay
    #   under 10 % of characters); (810, f"Page {n}", 9, "helv") — spec §4 Test Data.
    raise NotImplementedError


@pytest.fixture
def headingless_pdf(tmp_path) -> Path:
    """Uniform 10 pt text on 3 pages, no bookmarks — no deterministic candidate."""
    return _pdf(tmp_path / "plain.pdf", [[(80 + 18 * i, BODY, 10, "helv") for i in range(30)] for _ in range(3)])


class FakeAdapter:
    """Counts every adapter call; summaries return a fixed string."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def ask(self, prompt, structured_output=None, temperature=0.0, system_prompt=None):
        self.calls.append("ask")
        return "summary"

    async def ask_structured(self, *args, **kwargs):
        self.calls.append("ask_structured")
        raise AssertionError("structure prompt reached in a test that patches tree_parser")

    async def ask_with_finish_info(self, *args, **kwargs):
        self.calls.append("ask_with_finish_info")
        raise AssertionError("structure prompt reached in a test that patches tree_parser")

    async def ask_json(self, *args, **kwargs):
        self.calls.append("ask_json")
        raise AssertionError("structure prompt reached in a test that patches tree_parser")
```
Continue the same file with the six tests (second half of the module):
```python
async def test_no_adapter_layout(headed_pdf):
    """adapter=None → layout, no summaries, keys present, structure_source on every node (AC-5, AC-9)."""
    # FILL IN: result = await builder.build_page_index(str(headed_pdf), None); structure_source == "layout"; result keys
    #   == {doc_name, structure, structure_source, structure_report, _node_markdown, _pages, _segments}; no node has
    #   "summary"; every node of structure_to_list(result["structure"]) has structure_source "layout";
    #   structure_report["confidence"] >= 0.6.
    raise NotImplementedError


async def test_auto_falls_back_to_llm(headingless_pdf, monkeypatch):
    """Headingless PDF + adapter, tree_parser patched → llm, llm_used (AC-6)."""
    # FILL IN: monkeypatch builder.tree_parser with an async fake returning [{"title": "Doc", "start_index": 1, "end_index": 3}];
    #   options {"if_add_node_summary": "no"}; assert structure_source == "llm", report llm_used True, both candidates listed.
    raise NotImplementedError


async def test_llm_failure_falls_back_to_pages(headingless_pdf, monkeypatch):
    """Patched tree_parser raises → pages, llm_error set; segments retained (AC-6)."""
    # FILL IN: tree_parser fake raises RuntimeError("model down"); structure_source == "pages"; report llm_error contains
    #   "model down"; one root with 3 "Page n" children; result["_segments"] non-empty.
    raise NotImplementedError


async def test_modes_and_errors(headed_pdf, tmp_path):
    """Unknown mode / llm without adapter → ValueError; image-only → NoTextLayerError; bad bytes → UnreadablePDFError (AC-5, AC-8)."""
    # FILL IN: options {"structure_mode": "bogus"} → ValueError; {"structure_mode": "llm"} with adapter None → ValueError
    #   matching "needs an LLM adapter"; an image-only PDF (page.draw_rect only) → NoTextLayerError; a file containing
    #   b"%PDF-1.4 fake" → UnreadablePDFError; both errors are ValueError subclasses.
    raise NotImplementedError


@pytest.mark.parametrize("stage", ["analysis", "extraction", "segmentation", "empty"])
async def test_extraction_failure_is_explicit(headed_pdf, monkeypatch, stage):
    """Layout failures raise PDFStructureError naming the stage, cause chained; empty text raises (AC-19)."""
    # FILL IN: analysis → monkeypatch builder.analyze_layout to raise ValueError("boom"); extraction → builder.
    #   extract_markdown_per_page(path, **kwargs) raises ValueError("boom"); segmentation → builder.segment_pages raises
    #   ValueError("boom"); empty → extract_markdown_per_page returns [(n, "   ") for n in 1..4]. pytest.raises(PDFStructureError,
    #   match=stage if stage != "empty" else "produced no text"); __cause__ is the ValueError (None for "empty").
    raise NotImplementedError


async def test_layout_mode_summary_options(headed_pdf, monkeypatch):
    """Adapter + layout mode: no tree_parser; summaries call the adapter; both options off → zero calls (rev 0.2, AC-5)."""
    # FILL IN: tree_parser patched to raise AssertionError; (a) structure_mode "layout", if_add_node_summary "yes" → adapter.calls
    #   contains "ask" and nodes carry "summary"; (b) structure_mode "layout", summary "no", description "no" → adapter.calls == [].
    raise NotImplementedError
```
**Why this shape**: synthetic PDFs keep the test hermetic (no binary fixtures, spec §7); `FakeAdapter` makes any
unexpected structure prompt fail loudly, so "layout never calls a model for structure" is asserted, not assumed.
Async tests rely on pytest-asyncio auto mode (`asyncio_mode = auto`, pytest.ini:3 and
packages/ai-parrot/pyproject.toml:1099); sibling tests also decorate with `@pytest.mark.asyncio` — either works.

### `packages/ai-parrot/tests/knowledge/pageindex/test_builder_pages.py` (MODIFY — full rewrite)
```python
# occurrences: 1 (verified: grep -c 'def test_pages_returned_in_both_branches():' packages/ai-parrot/tests/knowledge/pageindex/test_builder_pages.py)
# REPLACE — the WHOLE file (all three existing tests reference the deleted _extract_node_markdown or count source text):
"""FEAT-845 M5 — build_page_index return contract and layout-stage propagation (replaces the FEAT-840 source count)."""
from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from parrot.knowledge.pageindex import builder  # noqa: E402
from parrot.knowledge.pageindex.layout import LayoutHeaders, PDFStructureError  # noqa: E402

KEYS = {"doc_name", "structure", "structure_source", "structure_report", "_node_markdown", "_pages", "_segments"}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.get_encoder", lambda model="gpt-4o": None)
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", lambda t, model="gpt-4o": max(1, len(t)))


@pytest.fixture
def small_pdf(tmp_path) -> Path:
    doc = pymupdf.open()
    try:
        for n in (1, 2):
            page = doc.new_page()
            page.insert_text((72, 100), f"Heading {n}", fontsize=16, fontname="hebo")
            for i in range(15):
                page.insert_text((72, 140 + 18 * i), "Plain body sentence for the page.", fontsize=10, fontname="helv")
        doc.save(str(tmp_path / "small.pdf"))
    finally:
        doc.close()
    return tmp_path / "small.pdf"


async def test_single_return_dict_keys(small_pdf):
    """One return dict with exactly KEYS (no doc_description without an adapter); _pages/_segments non-empty."""
    # FILL IN: result = await builder.build_page_index(str(small_pdf)); set(result) == KEYS; result["_pages"] and result["_segments"].
    raise NotImplementedError


async def test_layout_pages_propagates_errors(small_pdf, monkeypatch):
    """_layout_pages passes hdr_info=LayoutHeaders and wraps a failing stage as PDFStructureError."""
    # FILL IN: (a) fake extract_markdown_per_page(path, **kwargs) records kwargs and returns [(1, "# A\n\nx"), (2, "y")] →
    #   isinstance(kwargs["hdr_info"], LayoutHeaders) and segments returned; (b) fake raises FileNotFoundError →
    #   PDFStructureError matching "extraction", __cause__ preserved.
    raise NotImplementedError


async def test_layout_work_runs_in_threads(small_pdf, monkeypatch):
    """AC-16: get_page_tokens, analyze_layout, extract_markdown_per_page and segment_pages go through asyncio.to_thread."""
    # FILL IN: wrap asyncio.to_thread (monkeypatch builder.asyncio.to_thread) to record func.__name__ then delegate to the real
    #   one; after build_page_index the recorded names include all four.
    raise NotImplementedError


async def test_bytesio_skips_layout(small_pdf, monkeypatch):
    """BytesIO without an adapter: no layout analysis, page fallback, no pages or segments (spec §2)."""
    # FILL IN: monkeypatch builder.analyze_layout to raise AssertionError; result = await build_page_index(BytesIO(bytes));
    #   structure_source == "pages", result["_pages"] == [] and result["_segments"] == [].
    raise NotImplementedError
```
**Why this shape**: the old file pinned implementation text (`'"_pages": pages,'` twice); the rewrite pins behaviour —
the single return contract TASK-5341 consumes, the `hdr_info` hand-off, and AC-16's thread offload.

### FILL IN checklist
- [ ] `builder.py::build_page_index` — summary/description branch nested as today; bounded by spec §2 "Mode scope"
- [ ] `builder.py::_choose_structure` — LLM attempt, `llm_used`, `llm_error`, fall-through; bounded by spec §2 step 5, AC-6
- [ ] `test_builder_layout.py::headed_pdf` — fixture layout per spec §4 Test Data
- [ ] `test_builder_layout.py` — six test bodies per their stubs
- [ ] `test_builder_pages.py` — four test bodies per their stubs

---

## Acceptance Criteria

- [ ] AC-5: with `adapter=None`, `structure_mode="auto"` behaves as `"layout"`, summaries and the description are
  skipped, `"llm"` raises `ValueError`, an unknown mode raises `ValueError`; with an adapter, `layout` skips LLM
  structure generation but honours the summary/description options, and disabling both gives zero model calls.
- [ ] AC-6: no candidate reaching `structure_min_confidence` + an adapter in `auto` → `structure_source == "llm"`; when
  it raises → page fallback with `llm_error`; the page fallback keeps the extracted segments (also without an adapter).
- [ ] AC-8: no text on any page → `NoTextLayerError`; unreadable file → `UnreadablePDFError`; both `ValueError` subclasses.
- [ ] AC-9 (node part): every node of a PDF build carries `structure_source`; the return dict carries
  `structure_source` and `structure_report`.
- [ ] AC-16: layout analysis, extraction, segmentation (and `get_page_tokens`) run in worker threads.
- [ ] AC-19 (builder part): analysis / extraction / segmentation failure raises `PDFStructureError` naming the stage
  with the cause chained; empty extracted content raises; no contentless success.
- [ ] `_extract_node_markdown` is gone; TASK-5339's framing test still passes:
  `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/knowledge/pageindex/test_builder_framing.py -q`
  (owned by TASK-5339, so it is not one of this task's Validation Commands; the feature-level test contract runs it too).
- [ ] All tests pass (Validation Commands).
- [ ] `ruff check` is clean on `builder.py`, `utils.py`, `schemas.py`, `__init__.py`, `test_builder_layout.py`, `test_builder_pages.py`.
- [ ] Imports work: `from parrot.knowledge.pageindex import PDFStructureError, StructureReport, analyze_layout`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_builder_pages.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_pdf_to_markdown.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_builder_layout.py::test_no_adapter_layout` | `layout`, no summaries, the seven keys, `structure_source` on every node |
| `test_builder_layout.py::test_auto_falls_back_to_llm` | headingless PDF + adapter (tree_parser patched) → `llm`, `llm_used` |
| `test_builder_layout.py::test_llm_failure_falls_back_to_pages` | tree_parser raises → `pages`, `llm_error`, segments kept |
| `test_builder_layout.py::test_modes_and_errors` | unknown mode / llm without adapter → `ValueError`; image-only → `NoTextLayerError`; bad bytes → `UnreadablePDFError` |
| `test_builder_layout.py::test_extraction_failure_is_explicit` | parametrized stages + empty text → `PDFStructureError` naming the stage, cause chained |
| `test_builder_layout.py::test_layout_mode_summary_options` | adapter + layout: no tree_parser; summaries call the adapter; both off → zero calls |
| `test_builder_pages.py::test_single_return_dict_keys` | exactly the seven keys without an adapter |
| `test_builder_pages.py::test_layout_pages_propagates_errors` | `hdr_info` is a `LayoutHeaders`; a failing stage → `PDFStructureError` |
| `test_builder_pages.py::test_layout_work_runs_in_threads` | the four CPU-bound calls go through `asyncio.to_thread` |
| `test_builder_pages.py::test_bytesio_skips_layout` | BytesIO, no adapter → `pages`, no pages, no segments, no layout analysis |

(The two test blocks above are the scaffold.)

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-layout-structure --feature-id FEAT-845`)
2. **Read the spec** at the path listed above for full context (§2 Pipeline + rev 0.2 failure paragraph,
   "No adapter", "Mode scope", "Configuration"; §3 Module 5; §7 gotchas)
3. **Check dependencies** — TASK-5334, TASK-5335, TASK-5337 and TASK-5339 must be `"done"` in
   `sdd/tasks/index/pageindex-layout-structure.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" and every "Created by dependencies" name still exists
   - Re-grep the `builder.py` anchors (TASK-5339 shifted the line numbers; each anchor must still occur once)
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/pageindex-layout-structure.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands as
   `PYTHONPATH=packages/ai-parrot/src pytest <file> -q` (never `uv sync` inside the worktree)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5340 pageindex-layout-structure verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(filled by sdd-worker)*

**Completed by**: sdd-worker orchestrator, MCP seat, 1 attempt
**Date**: 2026-11-08
**Notes**: Merged into the feature branch; lint clean. Pageindex suite run directly on the host: only the 4 pre-existing failures (test_adapter x2, test_okf_ontology x2) that also fail on clean origin/dev. Engine background validation is capped at ~60s so it is not used. No review feedback recorded.
