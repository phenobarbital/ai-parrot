# TASK-5319: Documentation — pageindex-local-mcp.md, mcp-local-toolkits.md, pageindex.md

**Feature**: FEAT-842 — PageIndex Local MCP Toolkit
**Spec**: `sdd/specs/pageindex-local-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5314, TASK-5316, TASK-5317
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 6** and §10 (docs policy `required`). Operators need one page
that says how to install the `pageindex` local MCP toolkit, what is served with and
without `llm:`, and how storage and result bounds behave. The generic local-toolkits page
gets a short `pageindex` section, and the main PageIndex page links to the new one.

---

## Scope

- Create `wiki/knowledge/pageindex-local-mcp.md` from `sdd/templates/techwiki-page.md`
  (frontmatter `title:` + `summary:`). Content per spec §10:
  - install: `parrot toolkits install pageindex` (and `parrot self add pageindex` installs `ai-parrot[bookstore]`);
  - what is served without `llm:` and what `llm:` adds; the five hidden tools by name
    (`pageindex_insert_content`, `pageindex_import_file`, `pageindex_import_folder`,
    `pageindex_import_pdf`, `pageindex_search_documents_scoped`); no-LLM trees get
    `Section` types and no summaries, so BM25 indexes titles and bodies only;
  - constructor kwargs `storage_dir`, `max_result_chars` (only `retrieve` is bounded; the
    truncation marker text), `llm_client` (what `mcp-local` passes; exclusive with `adapter`), `has_llm`;
  - the `exclude: []` opt-in slot for the future agentic retrieval tool;
  - use FEAT-840's bounded `outline` over `get_tree` to browse large trees once it lands (spec §8);
  - two-writer behaviour (per-tree `flock` + signature reload, FEAT-831; two hosts on one repo are safe);
  - troubleshooting: `bm25s` missing (`parrot toolkits list` reports it), the `template_drift` message about a missing `exclude` key.
- Update `wiki/tools/mcp-local-toolkits.md`: insert a `` ## `pageindex` `` section (quickstart + link to the page above) **before** the `sdd-coder` section.
- Update `wiki/knowledge/pageindex.md`: add a Table of Contents link to `pageindex-local-mcp.md`.
- Create `tests/knowledge/pageindex/test_local_mcp_docs.py` (pattern: `test_generation_docs.py`).

**NOT in scope**: source changes; `wiki/_index.yaml` (no pageindex page is listed there today).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/pageindex-local-mcp.md` | CREATE | operator page |
| `wiki/tools/mcp-local-toolkits.md` | MODIFY | `pageindex` section before `sdd-coder` |
| `wiki/knowledge/pageindex.md` | MODIFY | Table of Contents link |
| `packages/ai-parrot/tests/knowledge/pageindex/test_local_mcp_docs.py` | CREATE | docs presence/link tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `1db2685b95`.

### Verified Imports
```python
from pathlib import Path   # only import the docs test needs (pattern: test_generation_docs.py)
```

### Existing Signatures to Use
```text
wiki/tools/mcp-local-toolkits.md:269   ## `sdd-coder` — orchestration kernel for the interactive sdd-worker (FEAT-549)    (occurrences: 1)
wiki/knowledge/pageindex.md:14          ## Table of Contents                                                             (occurrences: 1)
wiki/knowledge/pageindex.md:24          - [Generation Publication](pageindex-generation-publication.md)                 (occurrences: 1)
packages/ai-parrot/tests/knowledge/pageindex/test_generation_docs.py:5   REPO = Path(__file__).resolve().parents[5]
wiki/knowledge/pageindex-generation-publication.md:1-4   frontmatter shape: "---\ntitle: ...\nsummary: ...\n---"
sdd/templates/techwiki-page.md          sections: Purpose / Public API / Configuration & Parameters / Usage Examples / Gotchas / Related
```
Symbols the page documents (created by the dependencies): `PageIndexToolkit.llm_dependent_tools`,
`PageIndexToolkit.has_llm`, `llm_client=`, `max_result_chars=` (TASK-5314, TASK-5316);
`mcp/_toolkit_templates/pageindex.yaml`, `examples/pageindex-mcp.yaml` (TASK-5317).
Truncation marker (TASK-5316): `[truncated: N more characters in K further sections — lower top_k or narrow the query]`.

### Does NOT Exist
- ~~`parrot pageindex` CLI~~ — the commands are `parrot toolkits install pageindex` and `parrot mcp-local pageindex`
- ~~`pageindex_outline`~~ today — it is FEAT-840's; describe it as "when FEAT-840 lands"
- ~~a default model in the template~~ — the `llm:` line is commented out

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/knowledge/pageindex-local-mcp.md", "action": "CREATE"},
    {"path": "wiki/tools/mcp-local-toolkits.md", "action": "MODIFY"},
    {"path": "wiki/knowledge/pageindex.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_local_mcp_docs.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- `tests/docs/test_getting_started_claims.py::test_cited_components_exist` checks component
  names after `toolkits install` only in its `CLI_DOCS` (the getting-started guides), not in
  these wiki pages; it still passes once TASK-5317's template exists.
- FEAT-840's documentation task (TASK-5313) also edits `wiki/knowledge/pageindex.md`'s Table
  of Contents. Insert your line directly below the `Generation Publication` entry; whichever
  feature merges second resolves a one-line conflict.

---

## Implementation Blueprint

### Steps (in order)
1. Write the new page from the techwiki template — *why*: `parrot sdd techwiki check` expects its frontmatter and sections.
2. Insert the `pageindex` section into `mcp-local-toolkits.md` — *why*: operators scan that page for every local toolkit.
3. Add the ToC link — *why*: AC-13 requires the page to be linked.
4. Write the docs test — *why*: keeps the page from rotting silently.

### `wiki/knowledge/pageindex-local-mcp.md` (CREATE)
```markdown
---
title: PageIndex Local MCP Toolkit
summary: Serve per-repository PageIndex trees to Claude Code, Codex and Antigravity over stdio with `parrot mcp-local pageindex`; deterministic by default, LLM tools when `llm:` is set.
---

# PageIndex Local MCP Toolkit

## Purpose
<!-- FILL IN: one paragraph — what the server is, per-repo storage under .parrot/pageindex, no LLM by default -->

## Public API
- [`PageIndexToolkit`](ref:parrot.knowledge.pageindex.toolkit.PageIndexToolkit) — the toolkit the server exposes

## Configuration & Parameters
<!-- FILL IN: install commands; the seeded section (quote the template); storage_dir, max_result_chars,
     llm_client / llm:, has_llm; the five hidden tools; the exclude: [] opt-in slot -->

## Usage Examples
<!-- FILL IN: `parrot toolkits install pageindex`; `parrot mcp-local pageindex --config examples/pageindex-mcp.yaml`;
     a typical agent flow: create_tree -> insert_markdown -> search -> retrieve -->

## Gotchas
<!-- FILL IN: no-LLM trees (Section types, no summaries); retrieve truncation marker; get_tree is unbounded —
     prefer FEAT-840's outline once it lands; two writers are safe (flock + signature reload);
     bm25s missing; template_drift message about `exclude` -->

## Related
- [PageIndex](pageindex.md) — the document-tree plane
- [Generation Publication](pageindex-generation-publication.md) — storage layout, locks, two-writer safety
- [Local MCP toolkits](../tools/mcp-local-toolkits.md) — the generic `parrot mcp-local` / `parrot toolkits` machinery
```

### `wiki/tools/mcp-local-toolkits.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '## `sdd-coder` — orchestration kernel for the interactive sdd-worker (FEAT-549)' wiki/tools/mcp-local-toolkits.md) -->
<!-- BEFORE — insert above that heading (verified: mcp-local-toolkits.md:269) -->
## `pageindex` — per-repository document trees (FEAT-842)

<!-- FILL IN: 4-8 lines — what it serves, `parrot toolkits install pageindex`, no llm by default,
     add `llm:` for the five LLM tools, link to ../knowledge/pageindex-local-mcp.md -->

```

### `wiki/knowledge/pageindex.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '- [Generation Publication](pageindex-generation-publication.md)' wiki/knowledge/pageindex.md) -->
<!-- AFTER — insert below that line (verified: pageindex.md:24) -->
- [Local MCP Toolkit](pageindex-local-mcp.md)
```

### `packages/ai-parrot/tests/knowledge/pageindex/test_local_mcp_docs.py` (CREATE)
```python
"""The PageIndex local-MCP documentation is present and linked (FEAT-842)."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
PAGE = REPO / "wiki" / "knowledge" / "pageindex-local-mcp.md"


def test_page_has_frontmatter_and_names() -> None:
    text = PAGE.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: ")
    assert "\nsummary: " in text
    for name in (
        "parrot toolkits install pageindex",
        "storage_dir",
        "max_result_chars",
        "llm_client",
        "pageindex_insert_content",
        "pageindex_import_file",
        "pageindex_import_folder",
        "pageindex_import_pdf",
        "pageindex_search_documents_scoped",
        "exclude",
    ):
        assert name in text


def test_pages_link_new_page() -> None:
    pageindex = (REPO / "wiki" / "knowledge" / "pageindex.md").read_text(encoding="utf-8")
    assert "pageindex-local-mcp.md" in pageindex
    toolkits = (REPO / "wiki" / "tools" / "mcp-local-toolkits.md").read_text(encoding="utf-8")
    assert "## `pageindex`" in toolkits
    assert "pageindex-local-mcp.md" in toolkits
    # FILL IN: the pageindex section appears before the sdd-coder heading (index comparison)
```

### FILL IN checklist
- [ ] page body sections — bounded by spec §10 "Pages" list and the Scope bullets above
- [ ] `mcp-local-toolkits.md` section body — bounded by "4-8 lines + link"
- [ ] ordering assertion in the docs test

---

## Acceptance Criteria

- [ ] AC-13 the three pages exist/are updated and linked; `parrot sdd techwiki check --spec sdd/specs/pageindex-local-mcp-toolkit.spec.md --root .` passes (run it by hand; it is not a test runner).
- [ ] `test_local_mcp_docs.py` passes.
- [ ] `tests/docs/test_getting_started_claims.py` still passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_local_mcp_docs.py -q`
- `pytest packages/ai-parrot/tests/docs/test_getting_started_claims.py -q`

---

## Test Specification

See the CREATE block for `test_local_mcp_docs.py` above.

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5314, TASK-5316, TASK-5317 are `done`.
2. Mark `in-progress`; commit only the index.
3. Write the pages from the blueprint; run the Validation Commands and `parrot sdd techwiki check --spec sdd/specs/pageindex-local-mcp-toolkit.spec.md --root .`.
4. Commit the four files; `parrot sdd task close TASK-5319 pageindex-local-mcp-toolkit verified`; fill the Completion Note; commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
