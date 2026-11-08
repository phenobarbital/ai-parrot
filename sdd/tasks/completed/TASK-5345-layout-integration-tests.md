# TASK-5345: Layout structure integration tests (M11)

**Feature**: FEAT-845 — PageIndex Layout Structure Builder
**Spec**: `sdd/specs/pageindex-layout-structure.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5341, TASK-5342
**Assigned-to**: unassigned

---

## Context

Spec Module 11 and §4 "Integration Tests". The unit tasks prove each rule in isolation; this task
drives the whole pipeline through the public surface — `PageIndexToolkit.import_pdf` on a toolkit
with **no adapter** (no LLM reachable) — on the committed fixture PDF and on synthetic PDFs, plus one
scenario with a scripted adapter to prove the LLM fallback's prompts are framed end to end, and the
rev 0.2 scenarios: a failed extraction must not publish anything (and Bookstore reports it as
`BookstoreError`), and the page fallback must still publish a readable revision.

---

## Scope

- Create `test_layout_integration.py` with the five scenarios of spec §4 Integration Tests:
  `test_fixture_import_is_hybrid_and_anchored`, `test_fixture_read_pages_after_layout_import`,
  `test_low_confidence_pdf_uses_framed_llm`, `test_failed_extraction_does_not_publish`,
  `test_page_fallback_retains_content`.
- Build every synthetic PDF in `tmp_path` inside this module (no conftest).

**NOT in scope**: any production-code change (if a scenario fails, the bug belongs to the task that
owns that module — report it in the Completion Note / ledger, do not patch other tasks' files here);
unit-level rule tests (TASK-5333…5340); the evaluation (TASK-5344).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py` | CREATE | End-to-end scenarios |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit                 # toolkit.py:90
from parrot.knowledge.pageindex.segments import normalize_title, validate_ownership  # segments.py:305, :473
from parrot.knowledge.pageindex.segment_store import SegmentStore              # segment_store.py:25 (load_revision :64)
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION         # framing.py:10
from parrot.knowledge.pageindex.schemas import (PageIndexDetection, PhysicalIndexFix, TitleAppearanceCheck,
                                                TitleStartCheck, TocCompletionCheck, TocDetectionResult)  # schemas.py:11-90
from parrot.knowledge.pageindex.utils import structure_to_list                 # utils.py:294
from parrot.knowledge.bookstore.config import LibraryLocation                  # config.py:33
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError       # library.py:111, :178
import pymupdf                                                                  # 1.27.1
```

### Created by TASK-5333 (dependency, transitive)
```python
from parrot.knowledge.pageindex.layout import PDFStructureError   # (ValueError)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
PageIndexToolkit(adapter=None, storage_dir=..., ...)                            # :145 (adapter optional since FEAT-842)
async def create_tree(self, tree_name, doc_name=None) -> dict                   # :592
async def get_generation(self, tree_name) -> dict                               # :745
async def list_documents(self, tree_name) -> list[dict]                         # :853
async def read_pages(self, tree_name, doc_id, pages, max_chars=12000, cursor=None) -> dict  # :937
    # returns ReadResult.model_dump(): {"segments": [{"seq", "text", "start", "end", "address": {"page", ...}, ...}], ...}
    # (see test_read_tools.py:78-96 for the shape in use)
self._store.load(tree_name) -> dict                                             # :189 JSONTreeStore
async def _run_t3_classification(...)                                           # :486 — only runs when the tree already has
    # OKF-typed nodes (gate :526-527); a fresh tree has none, so a scripted adapter sees builder calls only

# packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py — names monkeypatched by this test:
#   extract_markdown_per_page (module global, imported at builder.py:15; called with hdr_info= after TASK-5340)
#   analyze_layout (module global after TASK-5340)
# packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py
#   ask_structured(prompt, output_type, temperature=0.0, system_prompt=None)   # :99
#   ask_with_finish_info(prompt, temperature=0.0, chat_history=None, system_prompt=None) -> (text, finish_reason)  # :151
#   ask_json(prompt, temperature=0.0, system_prompt=None)                       # :201
#   ask(prompt, structured_output=None, temperature=0.0, system_prompt=None)    # :61
# builder consumes: isinstance(result, TocDetectionResult) → result.toc_detected (:132-135);
#   TitleAppearanceCheck.answer (:646-647); TitleStartCheck.start_begin (:679-680);
#   generate_toc_init expects finish_reason == "finished" and a JSON list (:973-976)

# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
def validate_ownership(nodes, revision) -> list[str]                            # :473 ([] = partition holds)
# attach_level forces the FIRST top-level node's span to start at 0 (segments.py:397 `if top and valid:`)

# packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
Bookstore(locations, adapter=None, ...)                                         # store_no_llm = Bookstore(locations)
def list_books(self) -> list[BookCard]                                          # :329
async def add_book(self, file_path, scope="project", ...) -> tuple[BookCard, str]  # :1060

# Fixture facts (verified): arxiv_2408_09869.pdf — 9 pages; bookmarks [1 Introduction p1, 1 Getting Started p2,
#   1 Processing pipeline p2, 2 PDF backends p2, 2 AI models p3, 2 Assembly p4, 2 Extensibility p4,
#   1 Performance p4, 1 Applications p5, 1 Future work and contributions p5] == docling_structure.json
#   titles/depths/start_index. Printed headings carry numbers ("1 Introduction"); normalize_title strips them.
```

### Created by TASK-5340 / 5341 / 5342 (dependencies)
```python
# import_pdf(..., structure_mode="auto") result adds structure_source / structure_confidence / structure_report.
# PDFStructureError messages: "PDF layout {analysis|extraction|segmentation} failed for {name}: {exc}" and
#   "PDF layout extraction produced no text for {name}" (raised before import_pdf's write transaction).
# Bookstore maps PDFStructureError → BookstoreError("Cannot index <name>: <reason>").
# Hybrid on the fixture inserts Abstract, References, Appendix as top-level siblings (spec §2 Hybrid rule).
```

### Does NOT Exist
- ~~a shared conftest fixture for synthetic PDFs~~ — build them in this module
- ~~`PageIndexToolkit.import_pdf(..., adapter=...)`~~ — the adapter is a constructor argument
- ~~framing of summary / description prompts~~ — slice 5; this test disables summaries on the LLM scenario
- ~~`toolkit.read_pages(..., doc_id=None)`~~ — `doc_id` is required (take it from the import result)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.import_pdf",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.read_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#validate_ownership",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/framing.py#DATA_FRAMING_INSTRUCTION",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.add_book"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Offline: autouse stubs for `parrot.knowledge.pageindex.utils.get_encoder` (→ `None`),
  `parrot.knowledge.pageindex.utils.count_tokens`, `parrot.knowledge.pageindex.md_builder.count_tokens`
  and `parrot.knowledge.pageindex.toolkit.get_injection_scoring_engine` (→ `None`), brief item 10 and
  `test_segment_import.py:28-37`.
- Monkeypatched `extract_markdown_per_page` replacements must accept `(path, **kwargs)` — the builder
  passes `hdr_info=` by keyword (spec §7 gotcha).
- The framed-LLM scenario must pass `with_summaries=False`: summary/description prompts are not framed
  in this slice (spec Non-Goals), so they would break the "every call framed" assertion.
- AC-2's "span starts at a heading segment" holds for every bookmark node because the first top-level
  node on the fixture is the inserted `Abstract`; if hybrid did not insert it, `Introduction` would be
  forced to start at 0 by `attach_level` (segments.py:397) — report that as an M3/M5 bug, do not weaken
  the assertion.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module skeleton below (stubs, PDF builders, scripted adapter) — *why*: every scenario shares them.
2. Fill the fixture scenarios first (AC-1, AC-2, `read_pages`) — *why*: they validate the whole hybrid path on real data.
3. Fill the fallback scenarios (pages, framed LLM) and the failure scenario (tree + Bookstore) — *why*: AC-6, AC-7, AC-19.
4. Run the Validation Command; on a failing scenario, identify the owning task and record it instead of patching production code here.

### `packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py` (CREATE)
```python
"""FEAT-845 end to end: layout structure through import_pdf, fallbacks, and failure without publication."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION
from parrot.knowledge.pageindex.layout import PDFStructureError
from parrot.knowledge.pageindex.schemas import (PageIndexDetection, PhysicalIndexFix, TitleAppearanceCheck,
                                                TitleStartCheck, TocCompletionCheck, TocDetectionResult)
from parrot.knowledge.pageindex.segment_store import SegmentStore
from parrot.knowledge.pageindex.segments import normalize_title, validate_ownership
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.pageindex.utils import structure_to_list

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "arxiv_2408_09869.pdf"
REFERENCE = FIXTURES / "docling_structure.json"
SENTENCE = "Uniform body text sentence number {n} about deterministic structure."


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    approx = lambda text, model="gpt-4o": max(1, len(text or ""))  # noqa: E731
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.get_encoder", lambda model="gpt-4o": None)
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", approx)
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", approx)
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.get_injection_scoring_engine", lambda force_reresolve=False: None
    )


def _headed_pdf(path: Path) -> Path:
    """4 pages, 10 pt body, 16/12 pt headings (helv); a deterministic layout candidate."""
    # FILL IN: pymupdf build per brief item 11 / spec §4 headed_pdf — bounded by AC-3 fixture shape
    raise NotImplementedError


def _headingless_pdf(path: Path) -> Path:
    """Uniform 10 pt text (SENTENCE per page) on 3 pages, no bookmarks — no deterministic candidate."""
    # FILL IN: pymupdf build — bounded by spec §4 headingless_pdf
    raise NotImplementedError


class _ScriptedAdapter:
    """Records (method, prompt, system_prompt) for every call; answers so tree_parser completes (no TOC path)."""

    model = "scripted"
    client = None

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    # FILL IN: async ask_structured(prompt, output_type, temperature=0.0, system_prompt=None) returning
    #   TocDetectionResult(toc_detected="no"), PageIndexDetection(page_index_given_in_toc="no"),
    #   TocCompletionCheck(completed="yes"), TitleAppearanceCheck(answer="yes"), TitleStartCheck(start_begin="yes"),
    #   PhysicalIndexFix(physical_index="<physical_index_1>") (thinking="t" on each); async ask_with_finish_info
    #   returning ('[{"structure": "1", "title": "Part One", "physical_index": "<physical_index_1>"}]', "finished");
    #   async ask_json → []; async ask → "" — every method appends to self.calls — bounded by llm_adapter.py signatures


def _depths(nodes: list[dict[str, Any]], depth: int = 1) -> list[tuple[int, dict[str, Any]]]:
    out: list[tuple[int, dict[str, Any]]] = []
    for node in nodes:
        out.append((depth, node))
        out.extend(_depths(node.get("nodes") or [], depth + 1))
    return out


async def test_fixture_import_is_hybrid_and_anchored(tmp_path):
    """No adapter: hybrid; 10 reference titles at reference depths/starts; References + Appendix at depth 1;
    every bookmark node's span starts at a heading segment; ownership partitions the revision (AC-1, AC-2, AC-10)."""
    # FILL IN — bounded by AC-1, AC-2, AC-10 (no "anchor" key in the stored tree)
    raise NotImplementedError


async def test_fixture_read_pages_after_layout_import(tmp_path):
    """read_pages(tree, doc_id, "2") includes the `### **2 Getting Started**` heading segment with its address."""
    # FILL IN — bounded by spec §4 Integration Tests row 2
    raise NotImplementedError


async def test_low_confidence_pdf_uses_framed_llm(tmp_path):
    """Headingless PDF + scripted adapter, with_summaries=False: structure_source == "llm"; every call carries
    system_prompt == DATA_FRAMING_INSTRUCTION and page text only inside <document_text> (AC-6, AC-7)."""
    # FILL IN — bounded by AC-6, AC-7
    raise NotImplementedError


@pytest.mark.parametrize("failure", ["analysis", "extraction", "empty"])
async def test_failed_extraction_does_not_publish(tmp_path, monkeypatch, failure):
    """A failing layout stage raises PDFStructureError naming the stage; the tree and its revisions are
    unchanged; Bookstore (no LLM) maps the same failure to BookstoreError and publishes no book (AC-19)."""
    # FILL IN: import _headed_pdf into "t" first (success); snapshot copy.deepcopy(tk._store.load("t")) and
    #   await tk.get_generation("t"); patch builder.analyze_layout (raise ValueError) / builder.extract_markdown_per_page
    #   (raise ValueError, or return [(n, "") ...]) per `failure`; re-import → pytest.raises(PDFStructureError,
    #   match="analysis" | "extraction" | "produced no text"); tree + generation unchanged; then
    #   Bookstore([LibraryLocation("project", tmp_path/"proj"/"library"), LibraryLocation("global", tmp_path/"glob"/"library")])
    #   .add_book(pdf) → BookstoreError("Cannot index ..."), list_books() == [] — bounded by AC-19
    raise NotImplementedError


async def test_page_fallback_retains_content(tmp_path):
    """Headingless PDF, no adapter: structure_source == "pages", a revision exists, read_pages returns the original text (AC-6)."""
    # FILL IN — bounded by AC-6 (page fallback retains extracted segments)
    raise NotImplementedError
```
**Why this shape**: the toolkit is the public surface the spec's ACs speak about, so every scenario
goes through `import_pdf`. The scripted adapter answers with the schema instances the builder checks
with `isinstance` (builder.py:132-135, :646-647, :679-680), which keeps the no-TOC LLM path short and
deterministic while still exercising real prompt construction. Reference expectations are read from
`docling_structure.json` at runtime rather than hard-coded. The block is long because it carries the
shared helpers; the five test bodies are FILL INs.

### FILL IN checklist
- [ ] `_headed_pdf`, `_headingless_pdf` — synthetic PDFs; bounded by spec §4 fixtures
- [ ] `_ScriptedAdapter` methods — schema answers + call recording; bounded by llm_adapter.py signatures
- [ ] `test_fixture_import_is_hybrid_and_anchored` — AC-1, AC-2, AC-10
- [ ] `test_fixture_read_pages_after_layout_import` — heading segment on page 2
- [ ] `test_low_confidence_pdf_uses_framed_llm` — AC-6, AC-7
- [ ] `test_failed_extraction_does_not_publish` — AC-19 (toolkit + Bookstore)
- [ ] `test_page_fallback_retains_content` — AC-6

---

## Acceptance Criteria

- [ ] AC-1: fixture through `import_pdf` with no adapter → `structure_source == "hybrid"`, ten reference titles at reference depths and start pages, `References` and `Appendix` top-level; no LLM call possible.
- [ ] AC-2: every bookmark node's span starts at a `heading` segment; ownership partitions the revision.
- [ ] AC-6: low-confidence PDF with an adapter takes the LLM path; without an adapter the page fallback publishes a readable revision.
- [ ] AC-7 (end to end): every adapter call of the LLM structure path carries `DATA_FRAMING_INSTRUCTION`; page text appears only inside `<document_text>`.
- [ ] AC-10: no stored tree contains `anchor`.
- [ ] AC-19: analysis/extraction failure and empty extraction raise `PDFStructureError` naming the stage; the existing tree and revision are unchanged; Bookstore reports `BookstoreError` and publishes nothing.
- [ ] No production file changed by this task.
- [ ] All Validation Commands pass.
- [ ] `ruff check packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_fixture_import_is_hybrid_and_anchored` | hybrid; reference titles/depths/starts; References + Appendix depth 1; heading-segment span starts; `validate_ownership == []`; no `anchor` |
| `test_fixture_read_pages_after_layout_import` | page 2 read contains `### **2 Getting Started**` with `address.page == 2` |
| `test_low_confidence_pdf_uses_framed_llm` | `llm` source; all calls framed |
| `test_failed_extraction_does_not_publish` (×3) | stage-named `PDFStructureError`; tree/generation unchanged; Bookstore `BookstoreError`, no book |
| `test_page_fallback_retains_content` | `pages` source; revision present; original sentence readable |

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-layout-structure --feature-id FEAT-845`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5341 and TASK-5342 must be `"done"` in
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
9. **Close the task** with `parrot sdd task close TASK-5345 pageindex-layout-structure verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(filled by sdd-worker)*

**Completed by**: sdd-worker orchestrator, MCP seat, 1 attempt
**Date**: 2026-11-08
**Notes**: Merged into the feature branch; lint clean. Pageindex suite run directly on the host: only the 4 pre-existing failures (test_adapter x2, test_okf_ontology x2) that also fail on clean origin/dev. Engine background validation is capped at ~60s so it is not used. No review feedback recorded.
