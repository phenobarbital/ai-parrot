---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: the base_branch in sdd/config.json (or any non-hotfix branch)
# - type: hotfix              → base_branch MUST be the hotfix_base in sdd/config.json
type: feature
base_branch: dev
projects: [ai-parrot]  # FEAT-576 — carried from sdd/proposals/pageindex-tree-optimizer.brainstorm.md; only core files are touched (ai-parrot-tools is slice 4)
tags: [pageindex, pdf-structure, tree-optimizer, prompt-injection, mcp, bookstore]  # FEAT-576
docs:
  policy: required
  pages: [wiki/knowledge/pageindex-layout-structure.md]
  api_modules: [parrot.knowledge.pageindex.layout, parrot.knowledge.pageindex.layout_structure, parrot.knowledge.pageindex.layout_eval]
---

# Feature Specification: PageIndex Layout Structure Builder

**Feature ID**: FEAT-845
**Date**: 2026-11-08
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: 2.2.0

> Third of the six slices of `sdd/proposals/pageindex-tree-optimizer.brainstorm.md`
> (revision 4). It builds on FEAT-831 (`pageindex-generation-publication`) and FEAT-840
> (`pageindex-segment-store`), both merged, and runs alongside FEAT-843
> (`pageindex-agentic-retrieval`). It carries two hand-offs: FEAT-840 left the framing of the
> builder's own prompts to this slice, and FEAT-842 (`pageindex-local-mcp-toolkit`) left the
> removal of `pageindex_import_pdf` from `llm_dependent_tools` to it. Source paths below are
> relative to `packages/ai-parrot/src/parrot/` unless stated; line numbers were verified at
> `dev` @ `07d5ece62c` (FEAT-842 merged in PR #2029).

---

## 1. Motivation & Business Requirements

### Problem Statement

PDF structure in PageIndex is built entirely by the LLM. `build_page_index`
(`knowledge/pageindex/builder.py:1545`) hands the raw page text to `tree_parser`
(`builder.py:1436`), which asks the model to find a table of contents, transform it, assign
physical pages, verify every title (`check_title_appearance_in_start_concurrent`,
`builder.py:683`), repair the wrong ones and split large nodes recursively
(`process_large_node_recursively`, `builder.py:1366`). Concretely:

1. **It is the slowest and most expensive part of an import.** Thirteen prompt sites run in
   the structure pipeline alone, before any summary is written, and a TOC-less document goes
   through the no-TOC generator page group by page group.
2. **The PDF's own structure is ignored.** `Document.get_toc()` (embedded bookmarks) and the
   font data of every span are never read in `knowledge/pageindex/`. The repo's test fixture
   (`tests/knowledge/pageindex/fixtures/arxiv_2408_09869.pdf`) carries ten correct two-level
   bookmarks that the LLM pipeline re-derives at a cost.
3. **The segments FEAT-840 introduced have almost no headings.** The per-page markdown comes
   from `pymupdf4llm.to_markdown(page_chunks=True)` (`pdf_to_markdown.py:94-103`) with its
   default `IdentifyHeaders`, whose `body_limit` defaults to 12 pt
   (`pymupdf4llm/helpers/pymupdf_rag.py:89`): any heading at 12 pt or less is treated as body
   text. On the fixture, 1 of its 189 segments is a heading; the ten bookmarked section titles
   are plain paragraphs (`**1** **Introduction**`). `attach_pdf_document`
   (`segments.py:358`) can therefore only start a node's span at the first segment of its
   page, and the optimizer slice has no heading candidates to expand at.
4. **The builder's prompts are unframed.** None of the thirteen structure prompts uses
   `framing.py` or passes a system prompt (`PageIndexLLMAdapter` accepts one at
   `llm_adapter.py:66`), so text hidden in a PDF reaches the model as instructions. FEAT-840
   left this to slices 3 and 5.
5. **PDF import is impossible without a model.** FEAT-842 lists `pageindex_import_pdf` among
   the tools hidden when no `llm` is configured (`toolkit.py:135-143`), and Bookstore refuses PDFs outright when it
   has no LLM (`knowledge/bookstore/library.py:1130-1135`).

### Goals

- **Structure from the PDF itself.** Sources of structure are tried in order and scored for
  confidence: embedded **bookmarks** (rejected when non-monotonic or a per-page enumeration),
  **layout** headings from font statistics (size and weight relative to measured body text,
  running headers and footers excluded), a **hybrid** of the two when bookmarks are coarser
  than the printed headings, the existing **LLM** pipeline as fallback, and one node per
  **page** when nothing else works.
- **Headings become heading segments.** The per-page markdown is extracted with a
  layout-aware header detector, so every printed heading the builder uses is a `heading`
  segment and every structure node is anchored to the exact segment it starts at.
- **`structure_source`** (`bookmarks` | `layout` | `hybrid` | `llm` | `pages`) is recorded on
  every node of the imported subtree, returned by `import_pdf` with the confidence and a
  structure report, and listed by `list_documents`.
- **Deterministic PDF import.** `build_page_index` and `import_pdf` work with no adapter:
  structure from bookmarks or layout (or pages), no summaries, no description.
  `pageindex_import_pdf` leaves `llm_dependent_tools` (FEAT-842 hand-off) and Bookstore
  accepts PDFs without an LLM.
- **Framed fallback prompts.** Every prompt of the LLM structure pipeline wraps document text
  with `frame_text` and carries `DATA_FRAMING_INSTRUCTION` as its system prompt.
- **Explicit failures.** A PDF with no text layer is rejected with a clear error (OCR is out of
  scope); an unreadable PDF raises a clear error instead of a PyMuPDF `FileDataError`.
- **A measured threshold.** A deterministic evaluation script compares layout-built structure
  with LLM-built reference trees (the committed fixture and the local compliance corpus) and
  the default confidence threshold is set from its report.

### Non-Goals (explicitly out of scope)

- The optimizer (`pageindex-tree-optimizer`, slice 5): no normalize/merge/expand passes, no
  token cost model, no `key_items`, no bottom-up summaries. Layout-built leaves are as fine as
  the printed headings and are not split further by the LLM (`process_large_node_recursively`
  runs only on the LLM path, as today).
- Framing the **summary** and **doc-description** prompts (`generate_node_summary`,
  `builder.py:1496`; `generate_doc_description`, `builder.py:1527`): slice 5 rewrites both.
- Rewriting the LLM fallback's own logic (TOC detection, verification, fixing). It is reached
  less often and its prompts are framed; its decisions are unchanged.
- The brainstorm's optional spot-check of low-confidence headings with the light adapter.
  The existing check (`check_title_appearance`, `builder.py:604`) answers "does this title
  appear on this page", which this slice answers deterministically for bookmarks and which is
  true by construction for layout headings; asking "is this line a heading" would need a new
  prompt, and a low-confidence result already falls back to the LLM pipeline.
- OCR, `pymupdf_layout` (pymupdf4llm suggests it on stderr; it is not a dependency), and the
  layout path for `BytesIO` input (it keeps the LLM path, as today).
- Changing `structure_source` semantics for markdown, ebook or free-text imports: those nodes
  carry no `structure_source`.
- `multistoresearch` citations and the agentic loop (FEAT-843).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:767e670b173c673e4075420c4c20d89360e31b09a989658fa8940f0b0727d87e evaluation_digest=sha256:24f3c9ab72285f4d42e3d2f1a6b9eb1968d6918f6ed05b5d9c177b0a674ebeb6 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

**Pipeline.** For a PDF given by path, `build_page_index` becomes:

1. `get_page_tokens` (in a worker thread). An open failure raises `UnreadablePDFError`; a
   document with no non-whitespace text on any page raises `NoTextLayerError`. Both are
   `PDFStructureError(ValueError)` from the new `layout.py`, so tool callers see a message.
2. `analyze_layout(path)` (worker thread): one pass over `page.get_text("dict")` that measures
   body text, ranks heading sizes, finds running headers and footers, reads the bookmarks and
   collects standalone bold lines. The result is a `LayoutProfile`.
3. `extract_markdown_per_page(path, hdr_info=LayoutHeaders(profile))` (worker thread): the
   same per-page markdown as today, but with headings decided by the profile instead of
   pymupdf4llm's default `IdentifyHeaders`. Then `segment_pages(pages)` (worker thread, the
   FEAT-840 splitter, unchanged).
4. `build_structure(profile, segments, mode, min_confidence)` (pure, `layout_structure.py`)
   scores a **bookmarks** candidate and a **layout** candidate and returns the chosen
   structure, or nothing.
5. With nothing chosen: the LLM pipeline (`tree_parser`, prompts framed) when an adapter is
   configured and the mode allows it; one node per **page** otherwise, or when the LLM
   pipeline raises.
6. Node ids, optional summaries and description as today (skipped with no adapter), the
   `structure_source` stamped on every node, and a single return dict that adds
   `structure_source`, `structure_report` and `_segments` to the existing keys.

If step 2 or 3 fails (`ValueError`, `ImportError`, `FileNotFoundError`, logged), the build
continues with no pages and no segments: the LLM pipeline or the page fallback decides, and
`import_pdf` takes its existing no-segments path. `BytesIO` input skips steps 2–4 and keeps
today's behaviour (LLM pipeline, no pages). Segments are always produced by the layout-aware
extraction, whatever source wins, so one PDF yields one revision regardless of the structure
mode.

**Layout analysis (`analyze_layout`).** Spans are read with
`page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)` from a `pymupdf.Document` opened inside
the function (never shared across threads).
- *Running lines*: a text line in the top band (`y0 < 0.08 × page height`) or bottom band
  (`y1 > 0.92 × page height`) is keyed by its normalized text (casefold, whitespace collapsed,
  digit runs replaced by `#`). A key seen on at least `max(3, ceil(0.3 × page_count))` pages
  in the same band is running. Documents under 3 pages have none. Running lines are excluded
  from every statistic and are never headings; their text stays in the markdown verbatim.
- *Body size*: the character-weighted mode of `round(span.size)` over the remaining non-empty
  spans; ties go to the smaller size.
- *Heading sizes*: rounded sizes above the body size whose character share is at most 10 % of
  the counted text, largest first, at most `MAX_SIZE_LEVELS = 4`.
- *Standalone bold lines*: per page, lines at body size whose every non-empty span is bold
  (`span.flags & pymupdf.TEXT_FONT_BOLD`, or `"Bold"` in the font name), with at most 12 words,
  not ending in `.` or `,`, that are the only line of their block or the first line of a block
  whose other lines are not bold. Stored as normalized text per page.
- *Bookmarks*: `doc.get_toc(simple=True)` (`[level, title, page]`, page 1-based). Usable
  entries have a stripped title and `1 <= page <= page_count`; levels are normalized so a level
  never exceeds the previous one by more than 1. The bookmarks are **rejected**, with the
  reason recorded in `LayoutProfile.bookmark_rejection`, when there are fewer than 2 usable
  entries, when a page number ever decreases in document order (non-monotonic), or when they
  are a per-page enumeration: `page_count >= 4`, every entry at level 1, entries
  `>= 0.8 × page_count`, and at least 80 % of pages carrying exactly one entry or at least 80 %
  of titles matching `^(page|p\.?)?\s*\d+$` (case-insensitive).

**Header detector (`LayoutHeaders`).** pymupdf4llm calls `get_header_id(span, page)` for every
span and makes a line a heading when any of its spans returns a non-empty prefix
(`max_header_id`, `pymupdf_rag.py:425-431`). The decision, in order:
1. empty span text → `""`;
2. the span lies in a running line (same band, same normalized key) → `""`;
3. `round(span.size)` is a heading size at rank *i* (0-based) → `"#" * (i + 1) + " "`;
4. the span is bold, at body size, and its normalized text is contained in a standalone bold
   line of that page → `"#" * (len(heading_sizes) + 1) + " "` (the body-bold level);
5. the span is bold or above body size and its normalized text matches a usable bookmark title
   of the same page (`_titles_match`, `segments.py:312`: equality, or containment of at least
   3 characters) → the body-bold level;
6. otherwise `""`.

Levels come from layout alone (size rank, then the body-bold level); bookmarks only decide
*whether* a line is a heading (rule 5). A body line that merely contains a heading's words is
never promoted: rules 3–5 require a larger or bold span.

**Titles.** A heading segment's title is `heading_title(text)`: the ATX marker removed
(`_heading_text`, `segments.py:340`), emphasis markers stripped (`**`, `__`, surrounding `_`,
backticks, `~~` — pymupdf4llm wraps bold header lines in `**…**`,
`pymupdf_rag.py:623-631`), whitespace collapsed. `### **1 Introduction**` → `1 Introduction`.

**Bookmarks candidate.** Each usable bookmark is anchored to a heading segment on its page:
normalized equality first, then `_titles_match`; one heading segment anchors at most one
bookmark. A bookmark is *found* when it is anchored or when its normalized title is contained
in the emphasis-stripped, normalized text of any segment of its page (at least 3 characters).
`confidence = found / usable`; rejected bookmarks score 0.

**Layout candidate.** The heading segments whose text is not a running-line key and whose
title is non-empty. Fewer than 2 → confidence 0 (`"fewer than two headings"`). Otherwise
`confidence = clean × density_factor × start_factor`, rounded to 3 places, where `clean` is the
share of headings with at most 20 words not ending in `.`; `density_factor` is 1 when there are
at most 8 headings per page on average, else `8 / density`; `start_factor` is 1 when the first
heading is on a page `<= max(3, ceil(0.1 × page_count))`, else 0.5.

**Choice.** With `mode` in `auto` | `layout` and `min_confidence` (option
`structure_min_confidence`, provisional default 0.6, set by the evaluation in M10):
1. bookmarks confidence `>= min_confidence` → the bookmark tree, plus the layout headings the
   hybrid rule inserts. `structure_source` is `hybrid` when at least one heading was inserted,
   else `bookmarks`;
2. else layout confidence `>= min_confidence` → `layout`;
3. else nothing (the builder then runs the LLM pipeline in `auto` mode with an adapter, or
   builds the page fallback).
`mode="llm"` skips 1–2 (`structure_source="llm"`) and requires an adapter.

**Hybrid rule.** The anchored bookmarks map a heading *level* to a bookmark *depth* (for each
level, the most common depth among the bookmarks anchored at that level). Every heading segment
that anchors no bookmark is placed by its level `L`:
- `L` lower (shallower) than every mapped level → not structure; its text stays owned by the
  node it falls in (on the fixture: the document title `Docling Technical Report`);
- `L` mapped → that depth;
- `L` unmapped but deeper than some mapped level → `depth(M) + (L − M)`, where `M` is the
  deepest mapped level below `L`.
Items are ordered by their segment position (an unanchored bookmark sits at the first segment
of its page, ahead of headings on that page). On the fixture this keeps all ten bookmarks with
their levels and inserts `Abstract`, `References` and `Appendix` as top-level siblings,
because they share the level of the anchored chapter headings.

**Tree and pages.** Bookmark, layout and hybrid structures are all built from one flat,
document-ordered item list `(depth, title, page, anchor)` with a stack (depth clamped to
previous + 1). Page fields follow the convention of the LLM path, so `outline`, Bookstore's TOC
and `build_node_markdown_map` read every tree the same way (`utils.post_processing`,
`utils.py:426`): `start_index` is the item's page; `end_index` is the next item's page, minus 1
when the next item *appears at the start* of its page, or `page_count` for the last item; never
below `start_index`. An item appears at the start when its anchor segment is the first segment
of its page once running-line segments are skipped — the deterministic answer to the question
`check_title_appearance_in_start` (`builder.py:656`) asks the LLM. When the first item starts
after page 1, a `Preface` node covers the pages before it (as `add_preface_if_needed`,
`utils.py:410`, does on the LLM path).

**Page fallback.** One root node titled with the source name's stem, pages
`1..page_count`, whose children are one node per page titled `Page <n>`.

**Anchors.** Bookmark, layout and hybrid nodes carry a transient
`anchor: {"page": int, "ordinal": int}` naming their heading segment. `attach_pdf_document`
(`segments.py:358`) resolves it to that segment's `seq` before trying its title match, which
removes the containment ambiguity of two similar titles on one page, and removes the `anchor`
key from every node it visits. `import_pdf` strips any anchor left when no revision is attached.
Anchors never reach a stored tree.

**LLM fallback, framed.** The thirteen functions of the structure pipeline —
`toc_detector_single_page` (`builder.py:113`), `detect_page_index` (`:275`),
`check_if_toc_extraction_is_complete` (`:324`), `check_if_toc_transformation_is_complete`
(`:353`), `extract_toc_content` (`:382`), `toc_transformer` (`:440`), `toc_index_extractor`
(`:515`), `add_page_number_to_toc` (`:553`), `check_title_appearance` (`:604`),
`check_title_appearance_in_start` (`:656`), `single_toc_item_index_fixer` (`:721`),
`generate_toc_init` (`:943`) and `generate_toc_continue` (`:979`) — wrap every
document-derived value they interpolate (page text, grouped tagged pages, TOC content, raw and
cleaned TOC) in `frame_text(value, source="document")` (`framing.py:42`) and pass
`system_prompt=DATA_FRAMING_INSTRUCTION` (`framing.py:10`) on every adapter call, continuation
calls included (16 call sites, `builder.py:132-1016`). The `<physical_index_N>` tags stay
inside the frame. Their logic and return values are unchanged.

**No adapter.** `build_page_index(adapter=None)` is valid: `auto` behaves as `layout`, summaries
and the description are skipped with an info log, and `mode="llm"` raises
`ValueError("structure_mode='llm' needs an LLM adapter")`. An unknown mode raises
`ValueError`.

**Toolkit.** `import_pdf` gains `structure_mode: str = "auto"` and passes it through
`options`. It uses the builder's `_segments` when present (no second tokenization) and
otherwise segments `_pages` as today (so FEAT-840's fakes keep working). Its result adds
`structure_source`, `structure_confidence` and `structure_report`. `_documents_of`
(`toolkit.py:748`) also collects the root node's `structure_source`, and each
`list_documents` row reports it (`None` for markdown, ebook and legacy documents). Since
FEAT-842 the adapter is optional (`toolkit.py:147`, `has_llm` at `:361`): with none,
`import_pdf` passes `adapter=None` and the builder runs in layout mode without summaries.

**Bookstore.** The PDF branch of `add_book` no longer requires an LLM. It calls `import_pdf`
with `structure_mode="auto"` when an LLM is configured and `"layout"` otherwise, keeps
`with_summaries` / `with_doc_description` tied to `has_llm`, and turns `PDFStructureError` into
`BookstoreError("Cannot index <name>: <reason>")` so the CLI keeps its clean error. The
`_NullAdapter` is never called on this path.

**FEAT-842 hand-off.** `pageindex_import_pdf` leaves `PageIndexToolkit.llm_dependent_tools`
(`toolkit.py:140`); the `pageindex.yaml` template comment and `pageindex-local-mcp.md` stop
listing it as model-dependent; FEAT-842's two set assertions drop it
(`test_toolkit_no_llm.py:15-21`, `tests/mcp/test_pageindex_template.py:65-70`, where it moves
to the tools served without a model). Only that name is removed: FEAT-843 adds
`pageindex_agentic_retrieve` to the same set.

**Evaluation.** `python -m parrot.knowledge.pageindex.layout_eval` builds each given PDF with
`adapter=None, structure_mode="layout"` (no LLM call) and compares it with an LLM-built
reference tree: title recall at the top level and at all depths (reference `Preface` nodes
ignored), start-page agreement (|Δ| ≤ 1) on matched titles, node counts, each candidate's
confidence and the time taken. It writes JSON and markdown to `artifacts/logs/layout_eval/`
(gitignored) and suggests a threshold. Pairs flagged internal never print titles. The M10 task
runs it over the fixture (`fixtures/arxiv_2408_09869.pdf` + `docling_structure.json`, produced
by Gemini through `e2e_pdf_test.py`) and the three PDF trees of
`corpus/compliance_soc2_hipaa/` (`nist_800_53`, `nist_csf_2_0`, and `aicpa_tsc` as internal,
`manifest.yaml` marks it `redistributable: false`), then sets the default threshold from the
report.

**Configuration.** Two `ConfigLoader._DEFAULTS` keys (`utils.py:764`):
`structure_mode: "auto"` and `structure_min_confidence: 0.6`. The builder reads them with
`getattr(opt, ..., default)`, so a YAML default file without them keeps working.

### Component Diagram
```
import_pdf(structure_mode) ──► build_page_index(doc, adapter | None, options)
                                   │ get_page_tokens ─► UnreadablePDFError / NoTextLayerError
                                   │ analyze_layout(path) ─► LayoutProfile  (to_thread)
                                   │ extract_markdown_per_page(path, hdr_info=LayoutHeaders(profile))
                                   │ segment_pages(pages) ─► segments      (to_thread)
                                   ▼
                     layout_structure.build_structure(profile, segments, mode, min_conf)
                        ├─ bookmarks candidate ─┐  score, anchor to heading segments
                        ├─ layout candidate ────┤  score
                        └─ hybrid insertion ────┘  ─► (nodes with anchors, source) | None
                                   │ None ─► tree_parser (frame_text + DATA_FRAMING_INSTRUCTION)
                                   │           └─ raises ─► page_structure
                                   │ None, no adapter / layout mode ─► page_structure
                                   ▼
             {structure, structure_source, structure_report, _pages, _segments, _node_markdown}
                                   ▼
import_pdf: revision(_segments) ─► attach_pdf_document (anchor → seq, then drop anchor)
            ─► WriteTransaction (FEAT-831)  ─► result + structure_source/confidence/report
Bookstore.add_book (pdf, no LLM) ─► import_pdf(structure_mode="layout")
layout_eval ─► build_page_index(adapter=None, layout) vs reference tree ─► artifacts/logs/
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `knowledge/pageindex/builder.py::build_page_index` | modifies | New pipeline, optional adapter, framed fallback, new return keys |
| `knowledge/pageindex/pdf_to_markdown.py::extract_markdown_per_page` | extends | `hdr_info` keyword forwarded to `pymupdf4llm.to_markdown` only when given |
| `knowledge/pageindex/segments.py::attach_pdf_document` | modifies | Honours and removes `anchor` |
| `knowledge/pageindex/utils.py::ConfigLoader` | extends | Two option keys |
| `knowledge/pageindex/schemas.py::PageIndexNode` | extends | `structure_source` field |
| `knowledge/pageindex/toolkit.py::PageIndexToolkit` | modifies | `import_pdf(structure_mode)`, result keys, `list_documents` column; later `llm_dependent_tools` |
| `knowledge/pageindex/framing.py` | uses | `frame_text`, `DATA_FRAMING_INSTRUCTION` |
| `knowledge/bookstore/library.py::Bookstore.add_book` | modifies | PDF without LLM |
| `pymupdf` 1.27.1 / `pymupdf4llm` 0.0.27 | uses | `get_toc`, span dicts, `to_markdown(hdr_info=…)` |
| `mcp/_toolkit_templates/pageindex.yaml` (FEAT-842) | modifies | Comment only |

### Data Models
```python
# knowledge/pageindex/layout.py
StructureSource = Literal["bookmarks", "layout", "hybrid", "llm", "pages"]
StructureMode = Literal["auto", "layout", "llm"]


class PDFStructureError(ValueError):
    """A PDF cannot be indexed (base class; tool callers see the message)."""


class UnreadablePDFError(PDFStructureError):
    """PyMuPDF could not open the file."""


class NoTextLayerError(PDFStructureError):
    """No page carries any text (scanned PDF); OCR is not supported."""


class Bookmark(BaseModel):
    level: int                 # >= 1, never more than previous + 1
    title: str
    page: int                  # 1-based physical page


class RunningLine(BaseModel):
    key: str                   # casefolded, whitespace collapsed, digit runs -> "#"
    band: Literal["top", "bottom"]
    pages: int                 # distinct pages it recurs on


class LayoutProfile(BaseModel):
    page_count: int
    body_size: Optional[int] = None          # None when no countable text
    heading_sizes: list[int] = Field(default_factory=list)   # largest first, <= MAX_SIZE_LEVELS
    running: list[RunningLine] = Field(default_factory=list)
    bold_lines: dict[int, list[str]] = Field(default_factory=dict)  # page -> normalized lines
    bookmarks: list[Bookmark] = Field(default_factory=list)  # usable entries, document order
    bookmark_rejection: Optional[str] = None


# knowledge/pageindex/layout_structure.py
class CandidateScore(BaseModel):
    source: Literal["bookmarks", "layout"]
    confidence: float          # 0..1, 3 decimals
    entries: int               # usable bookmarks or heading segments considered
    anchored: int              # entries anchored to a heading segment
    rejected: Optional[str] = None


class StructureReport(BaseModel):
    source: StructureSource
    mode: StructureMode
    min_confidence: float
    confidence: Optional[float] = None       # chosen deterministic candidate; None for llm/pages
    candidates: list[CandidateScore] = Field(default_factory=list)
    inserted_headings: int = 0               # hybrid insertions
    body_size: Optional[int] = None
    running_lines: int = 0
    llm_used: bool = False
    llm_error: Optional[str] = None          # message when the LLM pipeline raised


class StructureResult(BaseModel):
    source: StructureSource
    structure: list[dict]                    # PageIndex nodes with transient "anchor"
    report: StructureReport
```

Node fields after this feature (all optional, `PageIndexNode` already allows extras,
`schemas.py:118-136`): `structure_source` on every node of a PDF import; `anchor` only between
the builder and `attach_pdf_document`.

### New Public Interfaces
```python
# knowledge/pageindex/layout.py
MAX_SIZE_LEVELS: int = 4

def analyze_layout(pdf_path: str) -> LayoutProfile: ...          # sync; call in a thread

class LayoutHeaders:
    def __init__(self, profile: LayoutProfile) -> None: ...
    def get_header_id(self, span: dict, page: Any = None) -> str: ...

# knowledge/pageindex/layout_structure.py
def heading_title(text: str) -> str: ...
def build_structure(profile: LayoutProfile, segments: Sequence[Segment], *,
                    mode: StructureMode = "auto", min_confidence: float = 0.6) -> StructureResult | None: ...
def page_structure(page_count: int, doc_name: str) -> list[dict]: ...

# knowledge/pageindex/builder.py (changed)
async def build_page_index(doc, adapter: Optional[PageIndexLLMAdapter] = None, options=None,
                           light_adapter=None, llm_concurrency=DEFAULT_LLM_CONCURRENCY) -> dict: ...

# knowledge/pageindex/toolkit.py (changed)
async def import_pdf(self, tree_name, pdf_path, parent_node_id=None, with_summaries=True,
                     with_doc_description=False, doc_id=None, structure_mode: str = "auto") -> dict: ...

# knowledge/pageindex/layout_eval.py
async def evaluate_pair(pair: EvalPair, *, min_confidence: float) -> EvalResult: ...
def suggest_threshold(results: Sequence[EvalResult], *, recall_floor: float = 0.8) -> Optional[float]: ...
def main(argv: Optional[list[str]] = None) -> int: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Layout analysis and header detector | no | — | Heuristic thresholds and span/line handling need judgement against real PDFs |
| M2: Layout-aware extraction hook | yes | `hdr_info: Any = None`; forwarded only when not `None`; `test_pdf_page_images.py:36` call shape unchanged | — |
| M3: Structure candidates and choice | no | — | Scoring, hybrid placement and page conventions need judgement |
| M4: Anchored attach | yes | Anchor lookup `(page, ordinal) -> seq` before title match; pop `anchor` on every visited node | — |
| M5: Builder orchestration | no | — | Control flow across fallbacks, threads and error types |
| M6: Framed fallback prompts | yes | The 13 functions and 16 call sites listed in §2; `frame_text(value, source="document")`; `system_prompt=DATA_FRAMING_INSTRUCTION` | — |
| M7: Toolkit integration | yes | Signatures and result keys in §2/§3; `_segments` reuse; anchor strip; `list_documents` column | — |
| M8: Bookstore PDF without an LLM | yes | Mode by `has_llm`; `PDFStructureError` → `BookstoreError("Cannot index …")` | — |
| M9: FEAT-842 hand-off | yes | Remove one name from `llm_dependent_tools`; template comment, wiki page and two test sets follow | — |
| M10: Evaluation and threshold | no | — | Choosing the threshold from the report is a judgement call |
| M11: Integration tests | yes | Scenarios in §4 | — |
| M12: Documentation | no | — | Prose; needs M10's numbers |

### Module 1: Layout analysis and header detector
- **Path**: `knowledge/pageindex/layout.py` (new)
- **Responsibility**: `analyze_layout` (running lines, body size, heading sizes, standalone bold
  lines, bookmarks and their rejection), `LayoutHeaders` (the pymupdf4llm `hdr_info` object),
  the error classes and the `StructureSource` / `StructureMode` literals.
- **Depends on**: `pymupdf`; `segments._titles_match` / `normalize_title` (existing)
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/layout.py  (new)
  from parrot.knowledge.pageindex.segments import _titles_match, normalize_title  # verified: segments.py:312, :305

  MAX_SIZE_LEVELS: int = 4
  RUNNING_BAND: float = 0.08            # top/bottom fraction of the page height
  RUNNING_MIN_SHARE: float = 0.3        # share of pages a running key must recur on (min 3 pages)

  class PDFStructureError(ValueError): ...
  class UnreadablePDFError(PDFStructureError): ...
  class NoTextLayerError(PDFStructureError): ...
  class Bookmark(BaseModel): ...
  class RunningLine(BaseModel): ...
  class LayoutProfile(BaseModel): ...

  def running_key(text: str) -> str:
      """Casefold, collapse whitespace, replace digit runs with '#'."""

  def analyze_layout(pdf_path: str) -> LayoutProfile:
      """One pass over every page's span dicts.

      Opens its own pymupdf.Document (never shared across threads). Raises UnreadablePDFError when
      PyMuPDF cannot open the file. Never raises for odd content: bad bookmarks are rejected with a
      reason, missing text yields body_size=None.
      """

  class LayoutHeaders:
      """pymupdf4llm ``hdr_info`` object driven by a LayoutProfile (rules 1-6 of spec §2)."""
      def __init__(self, profile: LayoutProfile) -> None: ...
      def get_header_id(self, span: dict, page: Any = None) -> str:
          """Return '' or '#'*level + ' '; ``page`` is the pymupdf Page (``page.number`` 0-based)."""
  ```

### Module 2: Layout-aware extraction hook
- **Path**: `knowledge/pageindex/pdf_to_markdown.py` (modifies `:39-126`)
- **Responsibility**: accept `hdr_info` and forward it to `pymupdf4llm.to_markdown`.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/pdf_to_markdown.py  (modifies pdf_to_markdown.py:39)
  def extract_markdown_per_page(
      pdf_path: str | Path, *, images_dir: str | Path | None = None, image_format: str = "png",
      dpi: int = 150, image_size_limit: float = 0.05,
      hdr_info: Any = None,                       # new
  ) -> list[tuple[int, str]]:
      """... hdr_info: forwarded to ``pymupdf4llm.to_markdown(hdr_info=...)`` only when not None;
      with None the call is byte-identical to before."""
  ```

### Module 3: Structure candidates and choice
- **Path**: `knowledge/pageindex/layout_structure.py` (new)
- **Responsibility**: `heading_title`, the bookmarks and layout candidates, their scores, the
  hybrid insertion, the flat-items-to-tree builder with page conventions and `Preface`, the
  choice, `page_structure`, and the report models.
- **Depends on**: M1 (`LayoutProfile`, `Bookmark`, `running_key`, literals); `segments.py`
  (`Segment`, `_titles_match`, `normalize_title`, `_heading_text`)
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/layout_structure.py  (new)
  from parrot.knowledge.pageindex.layout import LayoutProfile, StructureMode, StructureSource, running_key
  from parrot.knowledge.pageindex.segments import Segment, _heading_text, _titles_match, normalize_title  # verified: segments.py:33, :340, :312, :305

  class CandidateScore(BaseModel): ...
  class StructureReport(BaseModel): ...
  class StructureResult(BaseModel): ...

  def heading_title(text: str) -> str:
      """ATX marker and emphasis markers removed, whitespace collapsed."""

  def score_bookmarks(profile: LayoutProfile, segments: Sequence[Segment]) -> tuple[CandidateScore, list[dict]]:
      """Score and anchor the usable bookmarks; items are (depth, title, page, anchor) dicts."""

  def score_layout(profile: LayoutProfile, segments: Sequence[Segment]) -> tuple[CandidateScore, list[dict]]:
      """Score the heading segments; items carry depth = rank of the heading level."""

  def insert_layout_headings(bookmark_items: list[dict], profile: LayoutProfile,
                             segments: Sequence[Segment]) -> tuple[list[dict], int]:
      """Hybrid rule of spec §2; returns the merged item list and the number of inserted headings."""

  def items_to_tree(items: Sequence[dict], segments: Sequence[Segment], profile: LayoutProfile) -> list[dict]:
      """Stack-built tree; start/end pages per the LLM-path convention; Preface when needed."""

  def build_structure(profile: LayoutProfile, segments: Sequence[Segment], *,
                      mode: StructureMode = "auto", min_confidence: float = 0.6) -> Optional[StructureResult]:
      """Chosen bookmarks/hybrid/layout structure, or None when no candidate reaches min_confidence
      (always None for mode='llm'). The report lists both candidates."""

  def page_structure(page_count: int, doc_name: str) -> list[dict]:
      """One root titled Path(doc_name).stem with one 'Page <n>' child per page."""
  ```

### Module 4: Anchored attach
- **Path**: `knowledge/pageindex/segments.py` (modifies `attach_pdf_document`, `:358-427`)
- **Responsibility**: resolve `anchor` to a `seq` before the title match; drop `anchor` from
  every node visited.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/segments.py  (modifies segments.py:358)
  def attach_pdf_document(structure: list[dict], revision: DocumentRevision) -> None:
      """... A node carrying ``anchor = {"page": p, "ordinal": o}`` starts at the segment with that
      page and ordinal when one exists (before the title match); ``anchor`` is removed from every
      node visited, attached or not."""
  ```

### Module 5: Builder orchestration
- **Path**: `knowledge/pageindex/builder.py` (modifies `build_page_index`, `:1545-1621`;
  removes `_extract_node_markdown`, `:1624-1640`); `knowledge/pageindex/utils.py`
  (`ConfigLoader._DEFAULTS`, `:764-773`); `knowledge/pageindex/schemas.py`
  (`PageIndexNode`, `:118-136`); `knowledge/pageindex/__init__.py` (exports)
- **Responsibility**: the pipeline of §2 (threads, errors, choice, LLM and page fallbacks,
  `structure_source` stamping, optional summaries, single return dict).
- **Depends on**: M1, M2, M3
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/builder.py  (modifies builder.py:1545)
  from parrot.knowledge.pageindex.layout import (LayoutHeaders, NoTextLayerError, UnreadablePDFError,
                                                 analyze_layout)
  from parrot.knowledge.pageindex.layout_structure import build_structure, page_structure, StructureReport
  from parrot.knowledge.pageindex.segments import segment_pages        # verified: segments.py:231

  async def build_page_index(
      doc: str | BytesIO,
      adapter: Optional[PageIndexLLMAdapter] = None,                  # was required
      options: dict | config | None = None,
      light_adapter: Optional[PageIndexLLMAdapter] = None,
      llm_concurrency: int = DEFAULT_LLM_CONCURRENCY,
  ) -> dict:
      """Returns {doc_name, structure, structure_source, structure_report (dict), _node_markdown,
      _pages, _segments, doc_description?}. Raises UnreadablePDFError, NoTextLayerError, and
      ValueError for an unknown structure_mode or structure_mode='llm' without an adapter."""

  async def _layout_pages(doc: str) -> tuple[Optional[LayoutProfile], list[tuple[int, str]], list[Segment]]:
      """analyze_layout + layout-aware extraction + segment_pages, each in asyncio.to_thread;
      ([None], [], []) on ValueError/ImportError/FileNotFoundError (logged)."""

  # knowledge/pageindex/utils.py  (modifies utils.py:764)  _DEFAULTS gains
  #     "structure_mode": "auto", "structure_min_confidence": 0.6
  # knowledge/pageindex/schemas.py  (modifies schemas.py:132)  PageIndexNode gains
  #     structure_source: Optional[str] = None
  # knowledge/pageindex/__init__.py  exports LayoutProfile, NoTextLayerError, PDFStructureError,
  #     StructureReport, UnreadablePDFError, analyze_layout
  ```

### Module 6: Framed fallback prompts
- **Path**: `knowledge/pageindex/builder.py` (the 13 functions listed in §2)
- **Responsibility**: frame document-derived values and pass the system prompt on all 16
  adapter calls of the structure pipeline. No logic change.
- **Depends on**: `framing.py` (existing). Shares `builder.py` with M5.
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/builder.py  (modifies builder.py:113-1020)
  from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_text  # verified: framing.py:10, :42
  _FRAME_SOURCE = "document"
  # e.g. check_title_appearance (builder.py:604): "The given page_text is {frame_text(page_text, source=_FRAME_SOURCE)}."
  #      result = await adapter.ask_structured(prompt, TitleAppearanceCheck, system_prompt=DATA_FRAMING_INSTRUCTION)
  ```

### Module 7: Toolkit integration
- **Path**: `knowledge/pageindex/toolkit.py` (modifies `import_pdf`, `:1534-1616`;
  `_documents_of`, `:748-755`; `list_documents`, `:842-863`)
- **Responsibility**: `structure_mode`, `_segments` reuse, anchor strip on the no-revision
  path, result keys, `list_documents` column, LLM-facing docstring.
- **Depends on**: M5 (return keys), M4 (anchor consumption)
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/toolkit.py  (modifies toolkit.py:1534)
  async def import_pdf(self, tree_name: str, pdf_path: str, parent_node_id: Optional[str] = None,
                       with_summaries: bool = True, with_doc_description: bool = False,
                       doc_id: Optional[str] = None, structure_mode: str = "auto") -> dict[str, Any]:
      """Build a PageIndex subtree from a PDF and splice it into ``tree_name``.

      Structure comes from the PDF's bookmarks or printed headings when they are reliable, from the
      LLM otherwise (structure_mode='auto'); 'layout' never calls a model, 'llm' forces the LLM
      pipeline. Works without a configured model (no summaries then).

      Returns: {tree_name, new_node_ids, doc_name, doc_description, doc_id, revision,
                structure_source, structure_confidence, structure_report}
      """

  @staticmethod
  def _strip_anchors(nodes: list[dict[str, Any]]) -> None:
      """Remove the transient ``anchor`` key from every node (no-revision path)."""
  ```

### Module 8: Bookstore PDF without an LLM
- **Path**: `knowledge/bookstore/library.py` (modifies `add_book`, `:1129-1141`)
- **Responsibility**: drop the guard, choose the mode by `has_llm`, map `PDFStructureError`.
- **Depends on**: M7 (`structure_mode`), M1 (`PDFStructureError`)
- **Interface Skeleton**:
  ```python
  # knowledge/bookstore/library.py  (modifies library.py:1129)
  from parrot.knowledge.pageindex.layout import PDFStructureError
  # in add_book, fmt == "pdf":
  #     try:
  #         result = await toolkit.import_pdf(tree_name=staging, pdf_path=str(path),
  #             with_summaries=self.has_llm, with_doc_description=self.has_llm,
  #             structure_mode="auto" if self.has_llm else "layout")
  #     except PDFStructureError as exc:
  #         raise BookstoreError(f"Cannot index {path.name}: {exc}") from exc
  ```

### Module 9: FEAT-842 hand-off
- **Path**: `knowledge/pageindex/toolkit.py` (`llm_dependent_tools`, `toolkit.py:135-143`);
  `mcp/_toolkit_templates/pageindex.yaml` (`:10-11`);
  `tests/knowledge/pageindex/test_toolkit_no_llm.py` (`:15-21`);
  `tests/mcp/test_pageindex_template.py` (`:65-71`); `wiki/knowledge/pageindex-local-mcp.md`
  (`:61-67`)
- **Responsibility**: `"pageindex_import_pdf"` leaves `llm_dependent_tools`; the template
  comment, FEAT-842's two set assertions (the name moves to the tools served without `llm`)
  and its wiki page follow; a test imports the fixture PDF with a toolkit that has no adapter.
- **Depends on**: M7 (FEAT-842 is merged)
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/toolkit.py  (modifies toolkit.py:135-143)
  llm_dependent_tools: frozenset[str] = frozenset({
      "pageindex_insert_content", "pageindex_import_file", "pageindex_import_folder",
      "pageindex_search_documents_scoped",
      # plus whatever FEAT-843 added (pageindex_agentic_retrieve); only import_pdf is removed
  })
  ```

### Module 10: Evaluation and threshold
- **Path**: `knowledge/pageindex/layout_eval.py` (new); `knowledge/pageindex/utils.py`
  (threshold default, only when the report justifies a change)
- **Responsibility**: the evaluation CLI of §2; run it over the four pairs; set
  `structure_min_confidence` from `suggest_threshold`; record the metrics (no internal titles)
  in the task's Completion Note and in M12's page.
- **Depends on**: M5. Shares `utils.py` with M5.
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/layout_eval.py  (new)
  class EvalPair(BaseModel):
      label: str
      pdf: Path
      reference: Path            # JSON with a top-level "structure" list
      internal: bool = False     # never print titles for this pair

  class EvalResult(BaseModel):
      label: str
      internal: bool
      pages: int
      structure_source: str
      chosen_confidence: Optional[float]
      candidates: list[CandidateScore]
      reference_nodes: int
      layout_nodes: int
      recall_top: float          # reference depth-1 titles matched by any built node title
      recall_all: float          # all reference titles ("Preface" ignored)
      page_agreement: float      # matched titles whose start_index differs by <= 1
      seconds: float
      unmatched_titles: list[str] = Field(default_factory=list)   # always empty when internal

  class EvalReport(BaseModel):
      created_at: str
      min_confidence: float
      recall_floor: float
      results: list[EvalResult]
      suggested_min_confidence: Optional[float]

  async def evaluate_pair(pair: EvalPair, *, min_confidence: float) -> EvalResult:
      """build_page_index(pair.pdf, adapter=None, options={'structure_mode': 'layout', ...}) vs reference."""

  def suggest_threshold(results: Sequence[EvalResult], *, recall_floor: float = 0.8) -> Optional[float]:
      """Good pairs: recall_all >= floor. Without bad pairs: min good confidence rounded down to 0.05.
      With bad pairs: max bad confidence + 0.05 (rounded) when <= min good confidence, else None."""

  def main(argv: Optional[list[str]] = None) -> int:
      """--pair LABEL=PDF::TREE (repeatable) --internal LABEL (repeatable) --min-confidence F
      --recall-floor F --out DIR (default artifacts/logs/layout_eval). Writes <UTC>.json and <UTC>.md."""
  ```

### Module 11: Integration tests
- **Path**: `tests/knowledge/pageindex/test_layout_integration.py` (new)
- **Responsibility**: the fixture end to end through `import_pdf` on a toolkit constructed
  without an adapter (no LLM reachable): hybrid structure, anchored spans, `read_pages`,
  `list_documents`; framed LLM fallback on a low-confidence synthetic PDF with a mocked adapter.
- **Depends on**: M7, M8

### Module 12: Documentation
- **Path**: `wiki/knowledge/pageindex-layout-structure.md` (new); `wiki/knowledge/pageindex.md`,
  `wiki/knowledge/bookstore-codex.md` (update); `tests/knowledge/pageindex/test_layout_docs.py`
  (new)
- **Responsibility**: how structure is chosen, `structure_mode`, `structure_source`, the
  evaluation numbers, Bookstore PDFs without an LLM.
- **Depends on**: M10 (numbers), M7, M8

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_layout.py::test_body_size_and_heading_sizes` | M1 | Synthetic PDF (pymupdf `insert_text`, sizes 10/12/16): body 10, heading sizes `[16, 12]` |
| `test_layout.py::test_running_lines_excluded` | M1 | Header and page-number footer on every page are running; never headings; text kept |
| `test_layout.py::test_bold_standalone_lines` | M1 | Bold body-size standalone line recorded; bold run-in word inside a paragraph is not |
| `test_layout.py::test_bookmarks_usable_and_levels_normalized` | M1 | `set_toc` with a level jump and an out-of-range page → normalized, entry dropped |
| `test_layout.py::test_bookmarks_rejected_non_monotonic` | M1 | Decreasing page → `bookmark_rejection` names it |
| `test_layout.py::test_bookmarks_rejected_per_page_enumeration` | M1 | One `Page n` entry per page → rejected |
| `test_layout.py::test_header_detector_rules` | M1 | Rules 1–6 on hand-built span dicts; a body span containing a heading's words gets `""` |
| `test_layout.py::test_unreadable_pdf` | M1 | `b"%PDF-1.4 fake"` → `UnreadablePDFError` |
| `test_pdf_page_images.py::test_hdr_info_forwarded` | M2 | `hdr_info` reaches `to_markdown`; without it the existing call-shape assertion still holds |
| `test_layout_structure.py::test_heading_title` | M3 | `### **1 Introduction**`, `## **1** **Introduction**` → `1 Introduction` |
| `test_layout_structure.py::test_score_bookmarks_found_and_anchored` | M3 | Found ratio, anchors unique, title-in-paragraph counts as found but not anchored |
| `test_layout_structure.py::test_score_layout_factors` | M3 | Fewer than 2 headings → 0; sentence-like headings lower `clean`; density and start factors |
| `test_layout_structure.py::test_hybrid_insertion` | M3 | Same-level unbookmarked heading → sibling; deeper → child; shallower → not structure |
| `test_layout_structure.py::test_items_to_tree_pages_and_preface` | M3 | `end_index` convention with and without appear-at-start; `Preface` when the first item starts after page 1 |
| `test_layout_structure.py::test_choice_order_and_modes` | M3 | bookmarks > layout > None; `llm` mode → None; threshold respected |
| `test_layout_structure.py::test_page_structure` | M3 | Root titled by stem, one child per page |
| `test_segments.py::test_attach_prefers_anchor` | M4 | Two similar titles on one page: the anchored node starts at its own heading; `anchor` removed from all nodes |
| `test_builder_layout.py::test_no_adapter_layout` | M5 | Synthetic headed PDF, `adapter=None` → `layout`, no summaries, keys present, `structure_source` on every node |
| `test_builder_layout.py::test_auto_falls_back_to_llm` | M5 | Headingless PDF + mocked adapter (tree_parser patched) → `llm`, `llm_used` |
| `test_builder_layout.py::test_llm_failure_falls_back_to_pages` | M5 | Patched `tree_parser` raises → `pages`, `llm_error` set |
| `test_builder_layout.py::test_modes_and_errors` | M5 | Unknown mode, `llm` without adapter → `ValueError`; image-only PDF → `NoTextLayerError` |
| `test_builder_layout.py::test_layout_failure_keeps_import_alive` | M5 | `analyze_layout` raising `ValueError` → no `_pages`, page/LLM fallback |
| `test_builder_pages.py` (rewritten) | M5 | Replaces the source-count test with a behavioural check of the return keys; `_layout_pages` fallbacks |
| `test_builder_framing.py::test_structure_prompts_framed` | M6 | Every adapter call made by the 13 functions carries `system_prompt=DATA_FRAMING_INSTRUCTION`; page text sits inside `<document_text>`; a `</document_text>` in page text is neutralized |
| `test_layout_import.py::test_import_pdf_result_and_segments_reuse` | M7 | Result keys; `_segments` used (no second `segment_pages`); fake without `_segments` still works |
| `test_layout_import.py::test_list_documents_structure_source` | M7 | PDF row has the source; markdown row has `None` |
| `test_layout_import.py::test_anchor_stripped_without_revision` | M7 | No pages → no `anchor` in the stored tree |
| `bookstore/test_library.py::test_add_book_pdf_without_llm` | M8 | Real synthetic PDF, no LLM → book added, `_NullAdapter` never called |
| `bookstore/test_library.py::test_add_book_unreadable_pdf` | M8 | Fake PDF bytes → `BookstoreError("Cannot index …")` (replaces `test_add_book_pdf_requires_llm`) |
| `test_toolkit_no_llm.py`, `tests/mcp/test_pageindex_template.py` (FEAT-842, updated) | M9 | Sets without `pageindex_import_pdf`; served with no `llm`; adapter-less toolkit imports the fixture |
| `test_layout_eval.py::test_evaluate_fixture_pair` | M10 | Fixture vs `docling_structure.json`: `recall_top == 1.0`, `page_agreement == 1.0` |
| `test_layout_eval.py::test_suggest_threshold` | M10 | Separable, non-separable and all-good cases |
| `test_layout_eval.py::test_cli_internal_hides_titles` | M10 | Internal pair → no titles in JSON or markdown |
| `test_layout_docs.py` | M12 | Page frontmatter and key names; `pageindex.md` links it |

### Integration Tests
| Test | Description |
|---|---|
| `test_layout_integration.py::test_fixture_import_is_hybrid_and_anchored` | Fixture through `import_pdf` on a toolkit with no adapter: `structure_source == "hybrid"`, ten bookmark titles with reference pages and depths, `References` and `Appendix` at depth 1, every bookmark node's span starts at a `heading` segment, ownership partitions the revision |
| `test_layout_integration.py::test_fixture_read_pages_after_layout_import` | `read_pages("…", doc_id, "2")` returns the `### **2 Getting Started**` heading segment with its address |
| `test_layout_integration.py::test_low_confidence_pdf_uses_framed_llm` | Synthetic headingless PDF with a mocked adapter: LLM path taken, every prompt framed |
| existing segment and toolkit tests unchanged | `test_segment_import.py`, `test_segment_integration.py`, `test_read_tools.py`, `test_toolkit.py`, `test_pdf_to_markdown.py` |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/pageindex/test_layout.py
- packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py
- packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py
- packages/ai-parrot/tests/knowledge/pageindex/test_builder_framing.py
- packages/ai-parrot/tests/knowledge/pageindex/test_builder_pages.py
- packages/ai-parrot/tests/knowledge/pageindex/test_layout_import.py
- packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py
- packages/ai-parrot/tests/knowledge/pageindex/test_layout_eval.py
- packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py
- packages/ai-parrot/tests/knowledge/pageindex/test_segments.py
- packages/ai-parrot/tests/knowledge/pageindex/test_pdf_to_markdown.py
- packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py
- packages/ai-parrot/tests/knowledge/pageindex/test_segment_import.py
- packages/ai-parrot/tests/knowledge/pageindex/test_segment_integration.py
- packages/ai-parrot/tests/knowledge/pageindex/test_read_tools.py
- packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py
- packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py
- packages/ai-parrot/tests/knowledge/pageindex/test_local_mcp_docs.py
- packages/ai-parrot/tests/mcp/test_pageindex_template.py
- packages/ai-parrot/tests/knowledge/bookstore/test_library.py
markers: []

### Test Data / Fixtures
```python
# Synthetic PDFs are built in tmp_path with pymupdf (no binary fixtures added):
@pytest.fixture
def headed_pdf(tmp_path) -> Path:
    """4 pages, body 10 pt, headings 16/12 pt, running header 'ACME Manual' and page-number footer."""

@pytest.fixture
def bookmarked_pdf(tmp_path) -> Path:
    """headed_pdf plus doc.set_toc([[1, 'Intro', 1], [2, 'Scope', 1], [1, 'Usage', 3]])."""

@pytest.fixture
def headingless_pdf(tmp_path) -> Path:
    """Uniform 10 pt text on 3 pages, no bookmarks — no deterministic candidate."""

@pytest.fixture
def image_only_pdf(tmp_path) -> Path:
    """Pages with no text (drawn shapes only) — NoTextLayerError."""

FIXTURE = Path(__file__).parent / "fixtures" / "arxiv_2408_09869.pdf"          # existing, 9 pages, 10 bookmarks
REFERENCE = Path(__file__).parent / "fixtures" / "docling_structure.json"      # existing, Gemini-built reference
```

---

## 5. Acceptance Criteria

- [ ] AC-1 On the fixture, `build_page_index(FIXTURE, adapter=None)` returns
  `structure_source == "hybrid"`; its tree holds the ten `docling_structure.json` titles at the
  same depths and `start_index` values, and `References` and `Appendix` as top-level nodes.
  No LLM call is made.
- [ ] AC-2 On the fixture, every bookmark node of the imported subtree has a `span` starting at a
  segment of kind `heading`, and the layout-aware extraction yields at least ten heading
  segments (today: one).
- [ ] AC-3 Running headers and page-number footers present on every page of `headed_pdf` are
  never heading segments, and their text is still in the segments.
- [ ] AC-4 Non-monotonic bookmarks and per-page enumerations are rejected with the reason in the
  report; the layout candidate or a fallback is used instead.
- [ ] AC-5 With `adapter=None`, `structure_mode="auto"` behaves as `"layout"`, summaries and the
  description are skipped, and `"llm"` raises `ValueError`; an unknown mode raises `ValueError`.
- [ ] AC-6 When no candidate reaches `structure_min_confidence` and an adapter is configured,
  the LLM pipeline runs (`structure_source == "llm"`); when it raises, the result is the page
  fallback with `llm_error` in the report.
- [ ] AC-7 Every adapter call made by the 13 structure-pipeline functions passes
  `system_prompt=DATA_FRAMING_INSTRUCTION`, and every document-derived value they interpolate is
  inside `<document_text>`; their return values for the existing builder tests are unchanged.
- [ ] AC-8 A PDF with no text on any page raises `NoTextLayerError`; an unreadable file raises
  `UnreadablePDFError`; both are `ValueError` subclasses.
- [ ] AC-9 Every node of a PDF import carries `structure_source`; `import_pdf` returns
  `structure_source`, `structure_confidence` and `structure_report`; `list_documents` reports
  `structure_source` per document (`None` for markdown, ebook and legacy documents).
- [ ] AC-10 No stored tree contains an `anchor` key, with or without segments.
- [ ] AC-11 `import_pdf` does not segment twice when the builder returns `_segments`; FEAT-840's
  test fakes that return only `_pages` keep passing.
- [ ] AC-12 `extract_markdown_per_page` without `hdr_info` calls `to_markdown(path,
  page_chunks=True)` exactly as before (`test_pdf_page_images.py:36` passes unchanged).
- [ ] AC-13 Bookstore without an LLM adds a real PDF (deterministic structure, `card_origin ==
  "fallback"`) and never calls `_NullAdapter`; an unreadable PDF raises `BookstoreError` naming
  the file.
- [ ] AC-14 `"pageindex_import_pdf" not in PageIndexToolkit.llm_dependent_tools`; a toolkit with
  no adapter imports the fixture; a `pageindex` MCP section with no `llm` serves
  `pageindex_import_pdf`; the template comment and `pageindex-local-mcp.md` no longer list it as
  model-dependent.
- [ ] AC-15 `python -m parrot.knowledge.pageindex.layout_eval` with the fixture pair reports
  `recall_top == 1.0` and `page_agreement == 1.0`; internal pairs print no titles; the four-pair
  run is recorded (metrics only) and `structure_min_confidence` equals its suggestion or the
  Completion Note says why not.
- [ ] AC-16 Layout analysis, extraction and segmentation run in worker threads; nothing new
  blocks the event loop.
- [ ] AC-17 `wiki/knowledge/pageindex-layout-structure.md` exists with frontmatter and is linked
  from `wiki/knowledge/pageindex.md`; `bookstore-codex.md` states that PDFs work without an LLM
  (`parrot sdd techwiki check`).
- [ ] AC-18 No new dependency; all Validation Contract tests pass; `ruff check` is clean on
  touched files.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Paths relative to
> `packages/ai-parrot/src/parrot/` unless stated. Verified at `dev` @ `07d5ece62c`.

### Verified Imports
```python
from parrot.knowledge.pageindex.builder import build_page_index          # builder.py:1545; re-exported __init__.py:11
from parrot.knowledge.pageindex.pdf_to_markdown import extract_markdown_per_page, build_node_markdown_map  # pdf_to_markdown.py:39, :211; builder.py:15
from parrot.knowledge.pageindex.segments import (
    Segment, DocumentRevision, segment_pages, attach_pdf_document, normalize_title,
    _titles_match, _heading_text,
)                                                                         # segments.py:33, :59, :231, :358, :305, :312, :340
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_text  # framing.py:10, :42
from parrot.knowledge.pageindex.utils import ConfigLoader, get_page_tokens, get_pdf_name, structure_to_list, count_tokens  # utils.py:761, :130, :173, :294, :66
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter   # llm_adapter.py:42
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit          # toolkit.py:90; __init__.py:21
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError # library.py
import pymupdf                                                            # 1.27.1: Document.get_toc(simple=True), TEXT_FONT_BOLD == 16, TEXTFLAGS_TEXT == 195, FileDataError(RuntimeError)
import pymupdf4llm                                                        # 0.0.27: to_markdown(doc, *, hdr_info=None, page_chunks=False, ...)
```

### Existing Class Signatures
```python
# knowledge/pageindex/builder.py
DEFAULT_LLM_CONCURRENCY = 16                                             # :57
_LLM_SEMAPHORE: contextvars.ContextVar[Optional[asyncio.Semaphore]]      # :60
async def _limited_gather(coros, *, return_exceptions=False) -> list     # :65
async def toc_detector_single_page(...)                                  # :113  (adapter call :132)
async def detect_page_index(...)                                         # :275  (:294)
async def check_if_toc_extraction_is_complete(...)                       # :324  (:347)
async def check_if_toc_transformation_is_complete(...)                   # :353  (:376)
async def extract_toc_content(...)                                       # :382  (:394, :407, :421 — continuations carry chat_history)
async def toc_transformer(...)                                           # :440  (:467, :494)
async def toc_index_extractor(...)                                       # :515  (:547)
async def add_page_number_to_toc(...)                                    # :553  (:592)
async def check_title_appearance(item, page_list, start_index=1, adapter=None) -> dict      # :604 (:646)
async def check_title_appearance_in_start(title, page_text, adapter) -> str                 # :656 (:679)
async def check_title_appearance_in_start_concurrent(structure, page_list, adapter) -> list # :683
async def single_toc_item_index_fixer(...)                               # :721  (:745)
async def generate_toc_init(...)                                         # :943  (:973)
async def generate_toc_continue(...)                                     # :979  (:1016)
async def meta_processor(page_list, mode=None, ..., adapter=None, light_adapter=None) -> list[dict]  # :1277
async def process_large_node_recursively(node, page_list, opt, adapter, light_adapter=None) -> dict  # :1366
async def tree_parser(page_list, opt, adapter, light_adapter=None) -> list[dict]           # :1436
async def generate_node_summary(node, adapter) -> str                   # :1496 (not framed here — slice 5)
async def generate_summaries_for_structure(structure, adapter)          # :1510
async def generate_doc_description(structure, adapter) -> str           # :1527 (not framed here — slice 5)
async def build_page_index(doc, adapter, options=None, light_adapter=None,
                           llm_concurrency=DEFAULT_LLM_CONCURRENCY) -> dict  # :1545
    # :1572 opt = ConfigLoader().load(options); :1573 page_list = get_page_tokens(doc) (sync, in the loop)
    # :1589-1621 tree_parser → write_node_id → add_node_text → _extract_node_markdown → summaries;
    #   two return dicts, each with "_node_markdown" and "_pages"
def _extract_node_markdown(doc, structure) -> tuple[dict[str, str], list[tuple[int, str]]]  # :1624 (sync extraction)

# knowledge/pageindex/utils.py
def count_tokens(text, model="gpt-4o") -> int                            # :66
def get_page_tokens(pdf_path, model="gpt-4o", pdf_parser="PyMuPDF") -> list[tuple[str, int]]  # :130 (pymupdf.open → FileDataError on bad bytes; ValueError on bad path)
def get_pdf_name(pdf_path) -> str                                        # :173 (basename for str; PDF title or "Untitled" for BytesIO)
def write_node_id(data, node_id=0) -> int                                # :262
def structure_to_list(structure) -> list[dict]                           # :294
def list_to_tree(data) -> list[dict]                                     # :371 (rebuilds nodes with title/start/end/nodes only — drops extra keys)
def add_preface_if_needed(data) -> list[dict]                            # :410
def post_processing(structure, end_physical_index) -> list[dict]         # :426 (end = next start, -1 when next appear_start == "yes")
class ConfigLoader:                                                      # :761
    _DEFAULTS = {..., "if_add_node_text": "no"}                          # :764-773
    def _validate_keys(self, user_dict) -> None                          # :786 (unknown keys → ValueError)
    def load(self, user_opt=None) -> SimpleNamespace                     # :791 (merge at :802)

# knowledge/pageindex/pdf_to_markdown.py
def extract_markdown_per_page(pdf_path, *, images_dir=None, image_format="png", dpi=150,
                              image_size_limit=0.05) -> list[tuple[int, str]]  # :39
    # :94 kwargs: dict[str, object] = {"page_chunks": True}; :103 chunks = pymupdf4llm.to_markdown(path_str, **kwargs)
def build_node_markdown_map(structure, pages) -> dict[str, str]          # :211

# knowledge/pageindex/segments.py
SegmentKind = Literal["heading", "paragraph", "list", "table", "code", "caption", "other"]  # :13
class Segment(BaseModel): seq; kind; page; ordinal; section; level; text; tokens; sha16; flags; injection  # :33
class DocumentRevision(BaseModel): doc_id; revision; source; segmenter="v1"; scored_by; created_at; segments  # :59
def segment_pages(pages: list[tuple[int, str]]) -> list[Segment]         # :231 (ordinal restarts per page)
def normalize_title(title: str) -> str                                   # :305
def _titles_match(a: str, b: str) -> bool                                # :312 (equality or containment >= 3 chars)
def _heading_text(text: str) -> str                                      # :340
def attach_pdf_document(structure: list[dict], revision: DocumentRevision) -> None  # :358
    def start_of(node: dict) -> Optional[int]:                           # :373 (first heading on start page matching the title, else first segment)
def render_body(revision, node, children) -> str                         # :458
def validate_ownership(nodes, revision) -> list[str]                     # :473

# knowledge/pageindex/framing.py
DATA_FRAMING_INSTRUCTION: str                                            # :10
def frame_text(text: str, *, source: str, flagged: bool = False) -> str  # :42

# knowledge/pageindex/llm_adapter.py
class PageIndexLLMAdapter:                                               # :42
    async def ask(self, prompt, structured_output=None, temperature=0.0, system_prompt=None) -> str  # :61
    # ask_structured (:99), ask_with_finish_info (:151), ask_json (:201) all accept system_prompt

# knowledge/pageindex/schemas.py
class PageIndexNode(BaseModel):                                          # :118
    ... doc_id; revision; span; owned (:132); nodes; model_config = {"extra": "allow"}

# knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):
    tool_prefix = "pageindex"                                            # :133
    llm_dependent_tools: frozenset[str] = frozenset({... "pageindex_import_pdf" (:140) ...})  # :135-143 (FEAT-842)
    def __init__(self, adapter: Optional[PageIndexLLMAdapter] = None, storage_dir=None, ...,
                 *, llm_client: Optional[AbstractClient] = None, max_result_chars=None, **kwargs)  # :145 (adapter :147, llm_client :166)
    @property
    def has_llm(self) -> bool                                            # :361 (self._adapter is not None)
    async def _run_t3_classification(...)                                # :480 (adapter-None branch at :530)
    def _documents_of(self, tree) -> dict[str, dict[str, Any]]           # :748 (dict built at :754)
    async def list_documents(self, tree_name) -> list[dict[str, Any]]    # :842 (row dict :852-861)
    async def import_pdf(self, tree_name, pdf_path, parent_node_id=None, with_summaries=True,
                         with_doc_description=False, doc_id=None) -> dict[str, Any]  # :1534
        # :1558 build_page_index(doc=pdf_path, adapter=self._adapter, options={...}, light_adapter=...)
        # :1572 node_markdown = subtree.pop("_node_markdown"); :1573 pages = subtree.pop("_pages")
        # :1574 segments = await asyncio.to_thread(segment_pages, pages) if pages else []
        # :1598 attach_pdf_document(fresh["structure"], revision); :1604 _stage_node_markdown (no revision)

# knowledge/bookstore/library.py
class _NullAdapter:  ask → ""; ask_structured / ask_with_finish_info raise RuntimeError  # :149
class Bookstore:
    def has_llm(self) -> bool  (property)                                # :215
    def _toolkit(self, scope) -> PageIndexToolkit                        # :233 (_NullAdapter when no LLM)
    async def add_book(...)                                              # :1060
        # :1129-1141 pdf branch: guard :1130-1135, import_pdf :1136; outer except BaseException cleans staging and re-raises (:1230)

# pymupdf4llm/helpers/pymupdf_rag.py (site-packages, 0.0.27)
class IdentifyHeaders:  __init__(doc, pages=None, body_limit=12, max_levels=6)  # :71, body_limit default :89
class TocHeaders:       __init__(doc)  # :167 — calls doc.get_toc() on the ARGUMENT (:187): a path string raises AttributeError
def to_markdown(doc, *, pages=None, hdr_info=None, ..., page_chunks=False, ...)  # :303; hdr_info dispatch :415-423
    # max_header_id (:425-431): a line is a heading when any span returns a prefix; shortest prefix wins
    # header lines are wrapped in **…** when all spans are bold (:623-631); consecutive same-level header lines are joined
    # page chunk dict keys: metadata, toc_items, tables, images, graphics, text, words (:1212-1220)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `LayoutHeaders` | `pymupdf4llm.to_markdown` | `hdr_info=` object with `get_header_id(span, page)` | `pymupdf_rag.py:417-418` |
| `analyze_layout` | `pymupdf.Document.get_toc`, `Page.get_text("dict")` | method calls | pymupdf 1.27.1 |
| `build_structure` | `segments._titles_match`, `normalize_title`, `_heading_text` | function calls | `segments.py:312`, `:305`, `:340` |
| `build_page_index` | `extract_markdown_per_page(hdr_info=)`, `segment_pages` | `asyncio.to_thread` | `pdf_to_markdown.py:39`, `segments.py:231` |
| framed prompts | `frame_text`, `DATA_FRAMING_INSTRUCTION` | function call / `system_prompt=` | `framing.py:42`, `:10`; `llm_adapter.py:66` |
| `attach_pdf_document` anchors | `Segment.page` / `Segment.ordinal` | `(page, ordinal) → seq` map | `segments.py:38-39` |
| `import_pdf` | `build_page_index` `_segments`, `structure_*` keys | dict pop | `toolkit.py:1558-1574` |
| `Bookstore.add_book` | `import_pdf(structure_mode=)`, `PDFStructureError` | call / except | `library.py:1136` |

### Does NOT Exist (Anti-Hallucination)
- ~~`get_toc(` or any span-font read in `knowledge/pageindex/`~~ — bookmarks and font data are unused today
- ~~`structure_source`, `structure_mode`, `structure_min_confidence`~~ — no field, option or key anywhere in `knowledge/pageindex/`
- ~~`anchor` on nodes~~ — not produced or read by any code
- ~~`layout.py`, `layout_structure.py`, `layout_eval.py`~~ — none exist under `knowledge/pageindex/`
- ~~`NoTextLayerError`, `UnreadablePDFError`, `PDFStructureError`~~ — not defined; a scanned PDF currently goes into the LLM pipeline
- ~~a `hdr_info` parameter on `extract_markdown_per_page`~~ — it forwards only `page_chunks` and the image options
- ~~`system_prompt=` in `builder.py`~~ — no builder call passes one; no builder prompt uses `framing.py`
- ~~`pymupdf_layout`~~ — not installed and not to be added (pymupdf4llm only suggests it)
- ~~Bookstore PDF books~~ — the library is empty in both scopes; the evaluation corpus is the fixture and `corpus/compliance_soc2_hipaa/`
- ~~`list_to_tree` keeping extra keys~~ — it rebuilds nodes from title/start/end/nodes only, so anchors cannot pass through `post_processing`; M3 builds its own tree

### Edit Sites (Blueprint Anchors)

Verified against: `07d5ece62c`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_eval.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py` | MODIFY | `    image_size_limit: float = 0.05,` (signature) and `    kwargs: dict[str, object] = {"page_chunks": True}` | `pdf_to_markdown.py:45`, `:94` | 1, 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py` | MODIFY | `    def start_of(node: dict) -> Optional[int]:` (inside `def attach_pdf_document(structure: list[dict], revision: DocumentRevision) -> None:`) | `segments.py:373`, `:358` | 1, 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py` | MODIFY (M5) | `async def build_page_index(` … through `def _extract_node_markdown(` (removed) | `builder.py:1545`, `:1624` | 1, 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py` | MODIFY (M5/M6 imports) | `from .pdf_to_markdown import build_node_markdown_map, extract_markdown_per_page` | `builder.py:15` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py` | MODIFY (M6) | the 16 `await adapter.ask…(` calls of the 13 functions | `builder.py:132-1016` (see §6 signatures) | 16 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py` | MODIFY | `        "if_add_node_text": "no",` | `utils.py:772` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py` | MODIFY | `    owned: Optional[list[list[int]]] = None` | `schemas.py:132` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py` | MODIFY | `from .segment_store import SegmentStore` | `__init__.py:26` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY (M7) | `    async def import_pdf(` / `        segments = await asyncio.to_thread(segment_pages, pages) if pages else []` | `toolkit.py:1534`, `:1574` | 1, 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY (M7) | `                docs[doc_id] = {"revision": revision, "root_node_id": node.get("node_id"), "name": node.get("title")}` | `toolkit.py:754` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY (M7) | `                    "scored_by": rev.scored_by if rev else None,` | `toolkit.py:859` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY (M9) | `            "pageindex_import_pdf",` inside `    llm_dependent_tools: frozenset[str] = frozenset(` | `toolkit.py:135`, `:140` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `                        "PDF ingest needs an LLM to detect and structure "` (guard `:1130-1135`) and `                result = await toolkit.import_pdf(` | `library.py:1132`, `:1136` | 1, 1 |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex.yaml` | MODIFY (M9) | `    # Add a model to enable the LLM-dependent tools (import_pdf, insert_content,` | `pageindex.yaml:10` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_builder_pages.py` | MODIFY | `def test_pages_returned_in_both_branches():` (source-count test replaced) | `test_builder_pages.py:23` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py` | MODIFY | `def test_extract_markdown_per_page_unchanged_without_images_dir(tmp_path: Path) -> None:` (add a sibling test) | `test_pdf_page_images.py:36` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_segments.py` | MODIFY | append anchor tests | — | — |
| `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` | MODIFY | `async def test_add_book_pdf_requires_llm(store_no_llm, tmp_path):` (replaced) | `test_library.py:199` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py` | MODIFY (M9) | `    "pageindex_import_pdf",` inside `LLM_TOOLS = {` | `test_toolkit_no_llm.py:15`, `:19` | 1 |
| `packages/ai-parrot/tests/mcp/test_pageindex_template.py` | MODIFY (M9) | `    "pageindex_import_pdf",` inside `LLM_TOOLS = {` (move it to the no-`llm` expectations) | `test_pageindex_template.py:65`, `:69` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/pageindex/test_builder_framing.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_import.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_eval.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py` | CREATE | — | — | — |
| `wiki/knowledge/pageindex-layout-structure.md` | CREATE | — | — | — |
| `wiki/knowledge/pageindex.md` | MODIFY | `## Building Trees from PDFs` | `pageindex.md:168` | 1 |
| `wiki/knowledge/bookstore-codex.md` | MODIFY | ``Without an LLM, in-book and cross-book search require `bm25s`. Catalog search,`` | `bookstore-codex.md:84` | 1 |
| `wiki/knowledge/pageindex-local-mcp.md` | MODIFY (M9) | ``Without `llm:` the server serves every tool except the five that need a model, which the factory hides through`` and the list item `` - `pageindex_import_pdf` `` | `pageindex-local-mcp.md:61`, `:67` | 1, 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- CPU-bound PyMuPDF work (`analyze_layout`, `extract_markdown_per_page`, `segment_pages`,
  `get_page_tokens`) runs in `asyncio.to_thread`, each call opening its own `pymupdf.Document`;
  a Document is never shared across threads.
- Pure functions in `layout_structure.py` (no I/O, no logging side effects beyond `logger.debug`),
  so every rule is unit-testable on hand-built `Segment` lists and profiles.
- Pydantic v2 models for the profile, scores and report; `logging.getLogger(__name__)`.
- Reuse `segments.normalize_title` / `_titles_match` for every title comparison, so bookmarks,
  layout and `attach_pdf_document` agree on what "same title" means.
- Tests build their PDFs with pymupdf in `tmp_path` (`insert_text(fontsize=…, fontname="helv"
  / "hebo")`, `set_toc`); no new binary fixtures.

### Known Risks / Gotchas
- **Revisions change for re-imports.** Headings now carry `#` markers that the old extraction
  did not emit, so re-importing a PDF imported under FEAT-840 creates a new revision; the
  previous one is kept for the grace period, as for any re-import.
- **`TocHeaders` bug.** pymupdf4llm's `TocHeaders(doc)` calls `get_toc()` on its argument, not on
  the document it opened (`pymupdf_rag.py:187`); a path string raises `AttributeError`. Do not
  use it; `LayoutHeaders` reads bookmarks from `LayoutProfile`.
- **`IdentifyHeaders` default.** `body_limit=12` makes every heading at or below 12 pt body text
  (`pymupdf_rag.py:89`); `LayoutHeaders` replaces it rather than tuning it.
- **Emphasis in heading text.** Header lines arrive as `### **1 Introduction**`; always compare
  through `heading_title`. `normalize_title` alone does not strip `**`.
- **Bold-line noise.** Documents that set labels (`Note`, `Example 3`) in bold on their own line
  produce extra body-bold headings; in hybrid mode they may land at a mapped depth. The layout
  score's `clean` and density factors and the evaluation measure this; the threshold is the
  control.
- **Text in figures.** The analysis pass sees text inside figures that pymupdf4llm omits from the
  markdown; tiny figure fonts fall below body size, and the 10 % share cap keeps large figure
  labels out of the heading sizes. A heading size that never reaches the markdown simply
  produces no segment.
- **`ConfigLoader` rejects unknown keys** (`utils.py:786`): the two new keys must be in
  `_DEFAULTS`, and the builder reads them with `getattr` defaults.
- **`test_builder_pages.py` counts source text** (`'"_pages": pages,'` twice); the single return
  dict breaks it by design — replace it with a behavioural test (Edit Sites).
- **Monkeypatched extraction in tests** uses one-argument lambdas
  (`test_builder_pages.py:7`); new calls pass `hdr_info=` by keyword, so updated fakes must
  accept `**kwargs`.
- **FEAT-842 pins the five-name set** in `test_toolkit_no_llm.py:15-21` and
  `tests/mcp/test_pageindex_template.py:65-70` (served with `llm`, hidden without), and
  `test_local_mcp_docs.py:21` requires the wiki page to mention `pageindex_import_pdf` (it still
  will, as a tool available without a model). FEAT-843 also adds a name to
  `llm_dependent_tools`; M9 removes only `pageindex_import_pdf`.
- **`toolkit.py` is shared** with FEAT-843 (different methods): rebase before `/sdd-done`.
- **Internal corpus.** `aicpa_tsc` is `redistributable: false`; its titles must not appear in any
  committed file, wiki page or PR text — metrics only.
- **pymupdf4llm prints** "Consider using the pymupdf_layout package…" on import; harmless.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pymupdf` | 1.27.1 (already pinned) | bookmarks, span font data |
| `pymupdf4llm` | 0.0.27 (already pinned) | per-page markdown with a custom `hdr_info` |

No dependency is added.

---

## Decisions

```yaml
schema_version: 1
document_id: pageindex-layout-structure
entries:
  - id: pdf-structure-comes-from-the-pdf-first
    statement: In auto mode a PDF's structure comes from its bookmarks, then from its printed headings measured by layout statistics (or a hybrid of both), then from the LLM pipeline, then one node per page; the LLM pipeline is a fallback chosen only when no deterministic candidate reaches structure_min_confidence, and structure_source records which source won on every imported node.
    relation: constrains
    about: [knowledge-pageindex]
    targets: ["file:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py"]
    contradicts: []
    supersedes: []
    rationale: Structure was the slowest, most expensive and most injection-exposed part of an import, and well-made PDFs already carry it; a scored, deterministic first pass keeps the LLM for the documents that need it and makes PDF import possible without a model.
    rejected_alternatives: ["Keep the LLM pipeline as the default and use layout only as a hint", "Vendor upstream Flash or depend on the pageindex wheel", "Use pymupdf4llm IdentifyHeaders/TocHeaders unchanged"]
  - id: structure-nodes-anchor-heading-segments
    statement: Headings used for structure are produced as heading segments by the layout-aware header detector that also renders the revision's markdown, and every bookmark, layout or hybrid node is anchored to the segment it starts at; attach_pdf_document resolves the anchor before any title match and the anchor never persists in a stored tree.
    relation: requires
    about: [knowledge-pageindex]
    targets: ["file:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py", "file:packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py"]
    contradicts: []
    supersedes: []
    rationale: One detector for both the markdown and the structure guarantees that a node's start is an exact segment, which the optimizer's heading expansion and the citation layer build on; title matching alone is ambiguous when similar titles share a page.
    rejected_alternatives: ["Map nodes to segments by title match only", "Rewrite the markdown after extraction to insert heading markers"]
  - id: builder-structure-prompts-are-framed
    statement: Every adapter call of the LLM structure pipeline wraps document-derived text with frame_text and passes DATA_FRAMING_INSTRUCTION as its system prompt.
    relation: requires
    about: [knowledge-pageindex]
    targets: ["file:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py", "file:packages/ai-parrot/src/parrot/knowledge/pageindex/framing.py"]
    contradicts: []
    supersedes: []
    rationale: Text hidden in a PDF must reach the model as quoted data, the same contract FEAT-840 set for read tools and FEAT-843 for the agentic loop.
    rejected_alternatives: ["Regex-strip suspicious text before prompting", "Leave the fallback unframed because it runs less often"]
```

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:767e670b173c673e4075420c4c20d89360e31b09a989658fa8940f0b0727d87e evaluation_digest=sha256:24f3c9ab72285f4d42e3d2f1a6b9eb1968d6918f6ed05b5d9c177b0a674ebeb6 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools
- Unmapped tags: pdf-structure, prompt-injection, tree-optimizer
- Targets resolved: 4/4
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
      "server",
      "skills",
      "tools"
    ],
    "targets_resolved": 4,
    "targets_total": 4,
    "unmapped_tags": [
      "pdf-structure",
      "prompt-injection",
      "tree-optimizer"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:24f3c9ab72285f4d42e3d2f1a6b9eb1968d6918f6ed05b5d9c177b0a674ebeb6",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:767e670b173c673e4075420c4c20d89360e31b09a989658fa8940f0b0727d87e",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:84d78bee242dd625faf0f96c4c77ab842dcf56b9e1ba9540f94cefe713f616d2",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Structure source for PDFs — *Resolved in brainstorm*: our own extractor on PyMuPDF; no vendored Flash, no `pageindex` dependency.
- [x] Is a server with no `llm` a supported default, given PDF import needs an LLM until the layout builder lands? — *Resolved in brainstorm*: yes, it is the default mode. This spec makes PDF import work in it.
- [x] Injection policy for document text in prompts — *Resolved in brainstorm*: framed and flagged, never redacted; applied here to the LLM structure pipeline.
- [x] Hand-off from FEAT-840 — *Recorded there*: framing the builder's own prompts belongs to slices 3 and 5. This spec frames the structure pipeline; summaries and the description stay with slice 5.
- [x] Hand-off from FEAT-842 — *Recorded there*: when PDF import is deterministic, this spec removes `pageindex_import_pdf` from `llm_dependent_tools` (M9; FEAT-842 merged in PR #2029).
- [x] Should Bookstore accept PDFs without an LLM once structure comes from the PDF? — *Resolved (Jesus Lara, 2026-11-08)*: yes; deterministic structure, no summaries or description (M8).
- [x] How is the confidence threshold set? — *Resolved (Jesus Lara, 2026-11-08)*: by a deterministic evaluation over the local corpus — the committed fixture and the three PDF trees of `corpus/compliance_soc2_hipaa/` (AICPA metrics only) — with the fixture comparison also kept as a CI test (M10). The Bookstore library, first proposed as the corpus, is empty.
- [ ] Final `structure_min_confidence` default (provisional 0.6) — *Owner: M10 task*, from the evaluation report.
- [ ] Should body-size bold standalone lines count as headings when the document has no bookmarks, or only to confirm bookmarks? — *Owner: M10 task*: decide from the evaluation (recall vs. noise); the rule ships enabled.

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` · Status: skipped (exploration doc
> `sdd/proposals/pageindex-tree-optimizer.brainstorm.md` is `**Status**: exploration`, not
> `accepted`; `codex` is installed) · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/knowledge/pageindex-layout-structure.md` — create: how PDF structure is chosen
    (sources, scores, hybrid rule, page conventions), `structure_mode`, `structure_source`,
    `structure_min_confidence` and its evaluation (metrics only), errors, framing of the
    fallback, PDF import without a model.
  - `wiki/knowledge/pageindex.md` — update: the "Building Trees from PDFs" section and the "How
    It Works" steps describe the layout-first pipeline; link the new page.
  - `wiki/knowledge/bookstore-codex.md` — update: PDFs work without an LLM.
  - `wiki/knowledge/pageindex-local-mcp.md` — update (M9): `import_pdf` is available with no
    `llm`.
- **API modules**:
  - `parrot.knowledge.pageindex.layout`
  - `parrot.knowledge.pageindex.layout_structure`
  - `parrot.knowledge.pageindex.layout_eval`

---

## Worktree Strategy

- **Isolation**: one feature worktree, `feat-FEAT-845-pageindex-layout-structure`, from
  `origin/dev`; the `sdd-coder` engine gives each task its own sub-worktree.
- **Module dependency graph** (edge = needs):
  - M3 → M1 (imports `LayoutProfile`, `running_key`, the literals)
  - M5 → M1, M2, M3 (calls `analyze_layout`, `LayoutHeaders`, `extract_markdown_per_page(hdr_info=)`, `build_structure`)
  - M7 → M5 (pops `_segments`, `structure_*`), M4 (relies on anchor removal)
  - M8 → M7 (`structure_mode`), M1 (`PDFStructureError`)
  - M9 → M7
  - M10 → M5 (calls `build_page_index(adapter=None)`)
  - M11 → M7, M8
  - M12 → M10, M7, M8
  - M1, M2, M4, M6 have no incoming edge and can start together.
- **Shared files** (their tasks are serialized): `builder.py` (M5, M6); `utils.py` (M5, M10);
  `toolkit.py` (M7, M9).
- **Exclusive resources**: none (no lockfile, migration or native rebuild). M10's four-pair run
  reads the gitignored corpus in the main checkout; it is local evidence, not a CI step.
- **Cross-feature dependencies**: FEAT-831, FEAT-840 and FEAT-842 (merged). FEAT-843 runs in
  parallel and also edits `toolkit.py` (other methods) and `llm_dependent_tools`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-08 | Jesus Lara (with Claude) | Initial draft from the umbrella brainstorm (slice 3), the FEAT-840/842 hand-offs and two clarifications; re-anchored after FEAT-842 merged (PR #2029) |
