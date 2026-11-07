# TASK-5312: Segment store integration tests

**Feature**: FEAT-840 — PageIndex Segment Store
**Spec**: `sdd/specs/pageindex-segment-store.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5310, TASK-5311
**Assigned-to**: unassigned

---

## Context

Spec §4 *Integration Tests*. End-to-end checks across modules: a real PDF's pages through the
whole segment path to citable reads, readers during a re-import from another process, the Bookstore
server tool list, and a legacy tree that stays untouched until `index_segments`.

---

## Scope

- Create `tests/knowledge/pageindex/test_segment_integration.py` with the four tests below.

**NOT in scope**: any source change. If a test exposes a bug, record it in the Completion Note and
open a ledger issue (`wikitoolkit ledger open … --discovered-from spec:FEAT-840`) instead of fixing
another task's code here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/pageindex/test_segment_integration.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.pdf_to_markdown import extract_markdown_per_page   # pdf_to_markdown.py:39
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit                    # toolkit.py:63
from parrot.knowledge.pageindex.segment_store import SegmentStore                  # TASK-5302
```

### Existing Signatures to Use
```python
# Fixture PDF (has a text layer): packages/ai-parrot/tests/knowledge/pageindex/fixtures/arxiv_2408_09869.pdf
# Two-process pattern: tests/knowledge/pageindex/test_generation_integration.py (FEAT-831) — read it first and
#   reuse its subprocess helper shape.
# Bookstore stdio server: knowledge/bookstore/mcp_server.py (builds StdioMCPServer from BookstoreToolkit, :101);
#   tests/knowledge/bookstore/test_mcp_server.py shows how the server's tool list is inspected.
# Toolkit tools from earlier tasks: import_pdf(…, doc_id=None), read_pages, read_segments, list_documents,
#   outline, index_segments, retrieve, search.
```

### Does NOT Exist
- ~~an LLM-free real `build_page_index`~~ — keep monkeypatching `build_page_index` with a fake that returns a
  hand-made structure plus `_pages = extract_markdown_per_page(<fixture>)`; the real builder needs an LLM

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_segment_integration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py#extract_markdown_per_page"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- No network and no real LLM: MagicMock adapter as in `test_toolkit.py:19-48`, tiktoken stubbed.
- `extract_markdown_per_page` on the fixture runs pymupdf4llm locally; call it once per module (module-scoped fixture).
- Two-process test: the reader subprocess must construct its own `PageIndexToolkit` on the same `storage_dir`
  and only read; the host re-imports with a changed page text so a second revision appears. Each read must
  succeed and name one of the two revisions.

---

## Implementation Blueprint

### Steps (in order)
1. Module fixtures: adapter, tiktoken stub, fixture pages, fake builder factory.
2. The four tests.

### `packages/ai-parrot/tests/knowledge/pageindex/test_segment_integration.py` (CREATE)
```python
"""FEAT-840 integration tests: segments end to end."""

from pathlib import Path

import pytest

from parrot.knowledge.pageindex.pdf_to_markdown import extract_markdown_per_page
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

FIXTURE = Path(__file__).parent / "fixtures" / "arxiv_2408_09869.pdf"


@pytest.fixture(scope="module")
def fixture_pages() -> list[tuple[int, str]]:
    return extract_markdown_per_page(FIXTURE)


# FILL IN: adapter + toolkit fixtures and the autouse tiktoken stub — pattern test_toolkit.py:19-71
# FILL IN: fake_builder(pages) returning {"doc_name", "structure" (2 top-level nodes splitting the page range),
#   "_node_markdown": {}, "_pages": pages}


@pytest.mark.asyncio
async def test_segment_roundtrip_pdf_to_citation_address(toolkit, fixture_pages, monkeypatch):
    # FILL IN: import_pdf → list_documents → outline → read_pages("1-2"); for every read,
    #   stored = revision.segments[seq].text; assert read["text"] == stored[read["start"]:read["end"]]; label renders
    ...


@pytest.mark.asyncio
async def test_two_processes_read_during_reimport(tmp_path, fixture_pages, monkeypatch):
    # FILL IN: subprocess loops read_pages; host re-imports with modified pages; no failure; revisions ⊆ {R1, R2}
    ...


@pytest.mark.asyncio
async def test_bookstore_mcp_lists_new_tools(tmp_path):
    # FILL IN: build the Bookstore stdio server as test_mcp_server.py does; assert the three bookstore_read_*/outline tools
    ...


@pytest.mark.asyncio
async def test_legacy_tree_untouched_until_index_segments(toolkit, tmp_path):
    # FILL IN: create a FEAT-831 tree with add_node/update_node_content; record every file's mtime;
    #   search + retrieve + get_tree write nothing; read_pages raises KeyError naming pageindex_index_segments
    ...
```

### FILL IN checklist
- [ ] fixtures; bounded by Key Constraints
- [ ] four tests; bounded by AC-1..AC-4

---

## Acceptance Criteria

- [ ] AC-1: round trip on the real fixture PDF: every `read_pages` result satisfies `text == stored[start:end]` and has a `p. N ¶M` label.
- [ ] AC-2: a reader process never fails during a host re-import and only ever reports the old or the new revision.
- [ ] AC-3: the Bookstore stdio server lists `bookstore_read_pages`, `bookstore_read_segments`, `bookstore_outline`.
- [ ] AC-4: opening, searching and retrieving on a legacy tree writes no file; `read_pages` raises `KeyError` naming `pageindex_index_segments`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segment_integration.py -q`

---

## Test Specification

See the blueprint block above — the file *is* the test specification for this task.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-segment-store --feature-id FEAT-840`).
   Run tests with `PYTHONPATH=packages/ai-parrot/src` — the shared venv is editable-installed
   against the main checkout.
2. **Read the spec** at the path listed above for full context (§2 Overview is the design,
   §7 holds the splitter rules and the known risks).
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/pageindex-segment-store.json`.
4. **Verify the Codebase Contract** before writing code: re-run the `grep -c` of every MODIFY
   anchor; a count of `0` means drift — stop and report, do not invent an attachment point.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file.
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   within the constraint it names; touch only the files in *Files to Create / Modify*.
7. **Validate** — `ruff check --fix` on your files, then every command under *Validation Commands*.
8. **Commit code** (`feat(pageindex-segment-store): TASK-5312 — Segment store integration tests`), then close with
   `parrot sdd task close TASK-5312 pageindex-segment-store verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
