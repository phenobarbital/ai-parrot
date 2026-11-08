# TASK-5343: FEAT-842 hand-off — serve pageindex_import_pdf without a model (M9)

**Feature**: FEAT-845 — PageIndex Layout Structure Builder
**Spec**: `sdd/specs/pageindex-layout-structure.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5341
**Assigned-to**: unassigned

---

## Context

Spec §2 "FEAT-842 hand-off" and Module 9. FEAT-842 hides `pageindex_import_pdf` when a `pageindex`
MCP section has no `llm`, through `PageIndexToolkit.llm_dependent_tools` (`toolkit.py:135-143`),
because PDF import used to need a model. After TASK-5340/5341 a PDF imports deterministically with no
adapter, so the name leaves the set. The template comment, FEAT-842's two pinned set assertions and
its wiki page follow, and a test proves an adapter-less toolkit imports the committed fixture.
Only that one name is removed: FEAT-843 may have added `pageindex_agentic_retrieve` to the same set.

---

## Scope

- Remove `"pageindex_import_pdf"` from `PageIndexToolkit.llm_dependent_tools` (nothing else).
- Drop `import_pdf` from the model-dependent list in the `pageindex.yaml` template comment.
- `test_toolkit_no_llm.py`: remove the name from `LLM_TOOLS`; add a test that imports the fixture
  PDF with `PageIndexToolkit(storage_dir=tmp_path)` (no adapter) and gets `structure_source == "hybrid"`.
- `tests/mcp/test_pageindex_template.py`: remove the name from `LLM_TOOLS` and assert it is served
  without `llm` (both the factory test and the stdio test).
- `wiki/knowledge/pageindex-local-mcp.md`: "four" tools need a model; list item removed;
  `pageindex_import_pdf` named among the tools served without a model.
- `wiki/tools/mcp-local-toolkits.md` (`pageindex` section, :275-277): same correction — "the four
  tools that need a model", `pageindex_import_pdf` dropped from that list and named as working
  without a model. (Added at /sdd-task time: the page repeats the FEAT-842 claim this hand-off
  retires; FEAT-844's TASK-5332 lists the page as out of its scope, so no other task edits it.)

**NOT in scope**: `import_pdf` behaviour (TASK-5341); the new wiki page (TASK-5346).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | Remove one name from `llm_dependent_tools` |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex.yaml` | MODIFY | Template comment |
| `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py` | MODIFY | Set assertion + adapter-less fixture import |
| `packages/ai-parrot/tests/mcp/test_pageindex_template.py` | MODIFY | Set assertion; served without `llm` |
| `wiki/knowledge/pageindex-local-mcp.md` | MODIFY | "What is served" section |
| `wiki/tools/mcp-local-toolkits.md` | MODIFY | `pageindex` section: four model-dependent tools, import_pdf without a model |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# test_toolkit_no_llm.py (existing, :11-13)
from parrot.clients.base import AbstractClient
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
# New in test_toolkit_no_llm.py:
from parrot.knowledge.pageindex.utils import structure_to_list      # utils.py:294
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):
    llm_dependent_tools: frozenset[str] = frozenset({        # :135
        "pageindex_insert_content",                          # :137
        "pageindex_import_file",                             # :138
        "pageindex_import_folder",                           # :139
        "pageindex_import_pdf",                              # :140  <- removed
        "pageindex_search_documents_scoped",                 # :141
    })
    @property
    def has_llm(self) -> bool                                # :361
    async def create_tree(self, tree_name, doc_name=None) -> dict   # :592
    async def import_pdf(self, tree_name, pdf_path, ..., structure_mode="auto") -> dict  # :1546 (after TASK-5341)
    self._store.load(tree_name) -> dict                      # JSONTreeStore (:189)
# parrot/tools/toolkit.py:663  def list_tool_names(self) -> list[str]

# packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex.yaml
#   :10  "    # Add a model to enable the LLM-dependent tools (import_pdf, insert_content,"
#   :11  "    # import_file, import_folder, search_documents_scoped) and the LLM tree walk."

# packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py
LLM_TOOLS = {...5 names...}                                   # :15-21 ("pageindex_import_pdf" :19)
def _stub_tiktoken(monkeypatch)  (autouse)                    # :42-49 — stubs count_tokens only, NOT get_encoder
def test_llm_dependent_tools_names(tmp_path)                  # :108 (asserts == LLM_TOOLS at :111)

# packages/ai-parrot/tests/mcp/test_pageindex_template.py
LLM_TOOLS = {...5 names...}                                   # :65-71 ("pageindex_import_pdf" :69)
CORE_TOOLS = {"pageindex_search", "pageindex_retrieve", "pageindex_insert_markdown", "pageindex_create_tree"}  # :72
def test_factory_hides_llm_tools_without_llm(tmp_path)        # :223 (docstring "five" :224; asserts :228-229)
def test_factory_serves_llm_tools_with_llm(tmp_path, monkeypatch)  # :232 (docstring "five" :233)
def test_pageindex_serves_over_stdio(tmp_path)                # :251 (asserts :263-264)

# wiki/knowledge/pageindex-local-mcp.md
#   :61 "Without `llm:` the server serves every tool except the five that need a model, which the factory hides through"
#   :63-67 the five list items ("- `pageindex_import_pdf`" :67)
#   :70-74 "Everything else works with no model: ... With `llm:` set, the five hidden tools appear and" (:73)

# wiki/tools/mcp-local-toolkits.md  (## `pageindex` section, :268-280)
#   :275 "The template ships **without** an `llm:`: search is BM25 and the five tools that need a model"  (count 1)
#   :276 "(`pageindex_insert_content`, `pageindex_import_file`, `pageindex_import_folder`, `pageindex_import_pdf`,"  (count 1)
#   :277 "`pageindex_search_documents_scoped`) are hidden. Add an `llm:` line to the section to expose them and enable the LLM"
# packages/ai-parrot/tests/knowledge/pageindex/test_local_mcp_docs.py:13-25 — the page must still contain
#   the string "pageindex_import_pdf" (it stays, as a tool served without a model)

# Fixture: packages/ai-parrot/tests/knowledge/pageindex/fixtures/arxiv_2408_09869.pdf (9 pages, 10 bookmarks)
```

### Created by TASK-5340 / TASK-5341 (dependencies)
```python
# build_page_index(adapter=None) builds bookmark/layout/hybrid/pages structure without any model call.
# import_pdf result: {..., "structure_source", "structure_confidence", "structure_report"}; on the
# fixture with no adapter structure_source == "hybrid" (spec AC-1).
```

### Does NOT Exist
- ~~`pageindex_agentic_retrieve` in the set at /sdd-task time~~ — FEAT-843 may add it before this lands; never remove or assert against it here beyond what the file holds when you edit it
- ~~a `PageIndexToolkit.deterministic_tools` set~~ — there is only `llm_dependent_tools`
- ~~`create_toolkit_mcp_server(..., llm=...)`~~ — the factory reads `llm` from the section; tests configure it with `_configure_section`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex.yaml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/mcp/test_pageindex_template.py", "action": "MODIFY"},
    {"path": "wiki/knowledge/pageindex-local-mcp.md", "action": "MODIFY"},
    {"path": "wiki/tools/mcp-local-toolkits.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.llm_dependent_tools",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.import_pdf"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Remove exactly one set member. If FEAT-843 landed first and the set holds six names, the tests'
  `LLM_TOOLS` must mirror whatever remains (re-read `toolkit.py:135-143` before editing).
- The fixture import test runs the real builder: stub `parrot.knowledge.pageindex.utils.get_encoder`
  to return `None` and `parrot.knowledge.pageindex.toolkit.get_injection_scoring_engine` to return
  `None` (brief item 10; `test_segment_import.py:35-37`). The file's autouse fixture already stubs `count_tokens`.
- `toolkit.py` and `test_toolkit_no_llm.py` are also edited by FEAT-843/FEAT-844: rebase before `/sdd-done`.
- `wiki/tools/mcp-local-toolkits.md:275-277` repeats the "five tools that need a model" claim; it is in
  this task's file list (amended at /sdd-task time) — fix it with the same wording as `pageindex-local-mcp.md`.

---

## Implementation Blueprint

### Steps (in order)
1. Re-read `toolkit.py:135-143`; remove the one line — *why*: AC-14's core assertion; FEAT-843 may have changed the set.
2. Edit the template comment — *why*: the comment is what an operator reads when deciding whether to add `llm:`.
3. Update both test files' `LLM_TOOLS` and add the served-without-model assertions; add the fixture import test — *why*: FEAT-842 pinned the old set; AC-14 requires the adapter-less import.
4. Update the wiki section; run the Validation Commands — *why*: `test_local_mcp_docs.py` still requires the name on the page.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            "pageindex_import_pdf",' toolkit.py) — inside
# `    llm_dependent_tools: frozenset[str] = frozenset(` (verified: toolkit.py:135, count 1)
# DELETE toolkit.py:140
            "pageindex_import_pdf",
```
**Why**: spec M9 skeleton — only this name leaves; the comment above the set (:134) stays accurate.

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex.yaml` (MODIFY)
```yaml
# occurrences: 1 each (verified: grep -c on :10 and :11 of pageindex.yaml) — REPLACE pageindex.yaml:10-11
    # Add a model to enable the LLM-dependent tools (insert_content, import_file,
    # import_folder, search_documents_scoped) and the LLM tree walk. import_pdf works
    # without a model (structure from bookmarks / printed headings; no summaries).
```
**Why**: AC-14 — the template comment no longer lists `import_pdf` as model-dependent. Keep the
`# llm:` example line (:12) unchanged.

### `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py` (MODIFY)
```python
# (a) occurrences: 1 (verified: grep -c '    "pageindex_import_pdf",' test_toolkit_no_llm.py) — DELETE :19 inside `LLM_TOOLS = {` (:15)

# (b) APPEND at end of file
FIXTURE = Path(__file__).parent / "fixtures" / "arxiv_2408_09869.pdf"


async def test_import_pdf_without_adapter(tmp_path: Path, monkeypatch) -> None:
    """AC-14: an adapter-less toolkit serves and runs pageindex_import_pdf on the committed fixture."""
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.get_encoder", lambda model="gpt-4o": None)
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.get_injection_scoring_engine", lambda force_reresolve=False: None
    )
    tk = PageIndexToolkit(storage_dir=tmp_path)
    assert tk.has_llm is False
    assert "pageindex_import_pdf" in tk.list_tool_names()
    assert "pageindex_import_pdf" not in PageIndexToolkit.llm_dependent_tools
    await tk.create_tree("papers")
    result = await tk.import_pdf("papers", str(FIXTURE))
    # FILL IN: assert result["structure_source"] == "hybrid", result["doc_id"] and result["revision"]
    #   are set, and every node of tk._store.load("papers")["structure"] (walk with structure_to_list)
    #   carries structure_source — bounded by AC-1/AC-9/AC-14
    raise NotImplementedError
```
**Why this shape**: `Path` is already imported (:5). No adapter exists, so any model call would be an
`AttributeError` on `None` — success is itself the proof that no model was needed. Add the
`structure_to_list` import next to the existing imports.

### `packages/ai-parrot/tests/mcp/test_pageindex_template.py` (MODIFY)
```python
# (a) occurrences: 1 (verified: grep -c '    "pageindex_import_pdf",' test_pageindex_template.py) — DELETE :69
#     inside `LLM_TOOLS = {` (:65); add below CORE_TOOLS (:72, count 1):
NO_MODEL_PDF_TOOL = "pageindex_import_pdf"

# (b) test_factory_hides_llm_tools_without_llm — AFTER :229 `    assert CORE_TOOLS <= names`
#     (occurrences of that line: FILL IN: disambiguate — it also appears at :263 indented deeper;
#      quote the docstring line :224 to anchor)
    assert NO_MODEL_PDF_TOOL in names

# (c) test_pageindex_serves_over_stdio — AFTER :264 `        assert not (names & LLM_TOOLS)`
#     (occurrences: 1 with the 8-space indent — verified: grep -c '        assert not (names & LLM_TOOLS)';
#      the 4-space variant at :228 is the factory test)
        assert NO_MODEL_PDF_TOOL in names
```
**Why**: the name "moves to the tools served without a model" (spec §2). Update the two docstrings
that say "five" (:224, :233) to "four". The with-`llm` test keeps `LLM_TOOLS <= set(server.tools)`;
`pageindex_import_pdf` is served there too (it is in neither hidden set).

### `wiki/knowledge/pageindex-local-mcp.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c 'Without `llm:` the server serves every tool except the five that need a model, which the factory hides through' pageindex-local-mcp.md)
     REPLACE :61 "the five" -> "the four"; DELETE the list item :67 "- `pageindex_import_pdf`" (count 1) -->
Without `llm:` the server serves every tool except the four that need a model, which the factory hides through
<!-- in the "Everything else works with no model:" paragraph (:70-74): add `pageindex_import_pdf` (structure from the
     PDF's bookmarks or printed headings, no summaries; see pageindex-layout-structure.md) to the list, and
     REPLACE "the five hidden tools appear" (:73, count 1) with "the four hidden tools appear" -->
```
**Why**: AC-14 — the page stops listing `import_pdf` as model-dependent but still names it
(`test_local_mcp_docs.py:21`). The link target `pageindex-layout-structure.md` is created by TASK-5346;
a relative link to a page not yet present is fine for the docs test (it checks names only).

### `wiki/tools/mcp-local-toolkits.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF 'The template ships **without** an `llm:`: search is BM25 and the five tools that need a model' wiki/tools/mcp-local-toolkits.md)
     REPLACE :275-277 (the sentence ending "... are hidden.") with: -->
The template ships **without** an `llm:`: search is BM25 and the four tools that need a model
(`pageindex_insert_content`, `pageindex_import_file`, `pageindex_import_folder`,
`pageindex_search_documents_scoped`) are hidden. `pageindex_import_pdf` works without a model: structure comes from
the PDF's bookmarks or printed headings, with no summaries. Add an `llm:` line to the section to expose them and enable the LLM
<!-- keep the rest of :277-279 ("tree walk. `retrieve` output is bounded ...") unchanged; re-wrap to 120 columns -->
```
**Why**: the same FEAT-842 claim as `pageindex-local-mcp.md`; leaving it would contradict AC-14 in the
operator-facing toolkit catalog.

### FILL IN checklist
- [ ] `test_import_pdf_without_adapter` — result/stored-tree assertions; bounded by AC-1, AC-9, AC-14
- [ ] `test_pageindex_template.py` (b) — disambiguate the `CORE_TOOLS <= names` anchor (two occurrences at different indents)

---

## Acceptance Criteria

- [ ] AC-14: `"pageindex_import_pdf" not in PageIndexToolkit.llm_dependent_tools`; a toolkit with no adapter imports the fixture; a `pageindex` MCP section with no `llm` serves `pageindex_import_pdf`; the template comment and `pageindex-local-mcp.md` no longer list it as model-dependent.
- [ ] Only `pageindex_import_pdf` was removed from the set.
- [ ] `wiki/tools/mcp-local-toolkits.md` no longer lists `pageindex_import_pdf` among the hidden, model-dependent tools.
- [ ] All Validation Commands pass.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py packages/ai-parrot/tests/mcp/test_pageindex_template.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_pageindex_template.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_local_mcp_docs.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_toolkit_no_llm.py::test_llm_dependent_tools_names` (updated set) | set equals the four (or FEAT-843's) remaining names |
| `test_toolkit_no_llm.py::test_import_pdf_without_adapter` | no adapter; tool listed; fixture import → `hybrid`, revision set, `structure_source` on every node |
| `test_pageindex_template.py::test_factory_hides_llm_tools_without_llm` | `pageindex_import_pdf` served without `llm` |
| `test_pageindex_template.py::test_pageindex_serves_over_stdio` | same over stdio |
| `test_local_mcp_docs.py` (unchanged) | page still names `pageindex_import_pdf` |

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
9. **Close the task** with `parrot sdd task close TASK-5343 pageindex-layout-structure verified`
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
