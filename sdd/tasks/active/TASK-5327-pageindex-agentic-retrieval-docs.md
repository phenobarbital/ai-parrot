# TASK-5327: Documentation — wiki/knowledge/pageindex-agentic-retrieval.md

**Feature**: FEAT-843 — PageIndex Agentic Retrieval and Citations
**Spec**: `sdd/specs/pageindex-agentic-retrieval.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5325, TASK-5326
**Assigned-to**: unassigned

---

## Context

Spec §10 (docs policy `required`), Module 6, AC-15. Documents the API created by TASK-5320
(`read_ledger`), TASK-5322 (`citations`), TASK-5323/5324 (`agentic`), TASK-5325
(`agentic_retrieve`) and the opt-in template entry from TASK-5326.

---

## Scope

- Create `wiki/knowledge/pageindex-agentic-retrieval.md` from `sdd/templates/techwiki-page.md`
  (frontmatter `title:` / `summary:`): what stage 2 does; the ledger and why cursors are not one;
  the citation contract and EVERY rejection reason (`bad_address`, `revision_unread`,
  `revision_unavailable`, `segment_unread`, `empty_excerpt`, `excerpt_not_found`,
  `outside_covered_ranges`); bundle fields and every `stopped` value (`answered`, `budget`,
  `max_tool_calls`, `timeout`, `no_tool_calls`, `parse_error`) and their precedence; budgets
  (`agentic_budget_chars`, `agentic_max_reads`, `agentic_max_tool_calls`, `agentic_timeout_s`,
  the clipping below `_read`'s 500 floor); snapshot pinning; the dedicated client clone; the
  provider support table (tool loop: anthropic, google, openai, bedrock, gemma4, groq, grok, zai;
  none: hf, meta, local, vllm, moonshot, nvidia, jev); opt-in over MCP; a usage example.
- Public API links with `ref:` targets for `parrot.knowledge.pageindex.citations`,
  `parrot.knowledge.pageindex.read_ledger`, `parrot.knowledge.pageindex.agentic` symbols.
- Link it from `wiki/knowledge/pageindex.md` (after the Segment Store entry) and the `## Related`
  section of `wiki/knowledge/pageindex-segment-store.md`.
- Update `wiki/knowledge/pageindex-local-mcp.md` "The `exclude:` opt-in slot" paragraph (:79-83) and its
  config block (`exclude: []` at :44) to the shipped `exclude: [pageindex_agentic_retrieve]`, linking the new page.
- Create `tests/knowledge/pageindex/test_agentic_docs.py` (pattern of `test_generation_docs.py`).

**NOT in scope**: code changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/pageindex-agentic-retrieval.md` | CREATE | New techwiki page |
| `wiki/knowledge/pageindex.md` | MODIFY | TOC link |
| `wiki/knowledge/pageindex-segment-store.md` | MODIFY | Related link |
| `wiki/knowledge/pageindex-local-mcp.md` | MODIFY | exclude slot now filled |
| `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_docs.py` | CREATE | Docs test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pathlib import Path   # docs test only; REPO = Path(__file__).resolve().parents[5] (test_generation_docs.py:5)
```

### Existing Signatures to Use
```text
wiki/knowledge/pageindex.md:26                 - [Segment Store](pageindex-segment-store.md)
wiki/knowledge/pageindex-segment-store.md:142  ## Related
wiki/knowledge/pageindex-local-mcp.md:44       exclude: []           (config example)
wiki/knowledge/pageindex-local-mcp.md:79-83    ### The `exclude:` opt-in slot (says "a later slice … will be listed there")
sdd/templates/techwiki-page.md                 sections: Purpose / Public API / Configuration & Parameters / Usage Examples / Gotchas / Related
```
Symbols to document (verify names in the merged code before writing): `ReadLedger`, `LedgerEntry`,
`BudgetExhausted`, `Citation`, `ProposedCitation`, `RejectedCitation`, `validate_citations`,
`render_citation`, `render_citations`, `parse_address_key`, `AgenticAnswer`, `EvidenceBundle`,
`AgenticRetriever`, `clone_for_tools`, `PageIndexToolkit.agentic_retrieve`.

### Does NOT Exist
- ~~Bookstore `agentic_retrieve`~~ / ~~`multistoresearch` citations~~ — follow-ups (spec §8); say so, do not document them as available.
- ~~a `supports_tool_loop` client flag~~ — open question, not shipped.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/knowledge/pageindex-agentic-retrieval.md", "action": "CREATE"},
    {"path": "wiki/knowledge/pageindex.md", "action": "MODIFY"},
    {"path": "wiki/knowledge/pageindex-segment-store.md", "action": "MODIFY"},
    {"path": "wiki/knowledge/pageindex-local-mcp.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_agentic_docs.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- `ref:` links must resolve, or `parrot sdd techwiki check` fails (dangling refs broke publishes before).
- Keep examples truthful: the default budgets are provisional (spec §8).

---

## Implementation Blueprint

### Steps (in order)
1. Write the page from the template.
2. Add the three links / the local-mcp update.
3. Write the docs test; run it and the techwiki check.

### `pageindex-agentic-retrieval.md` (CREATE)
```markdown
---
title: PageIndex Agentic Retrieval and Citations
summary: Bounded stage-2 reading loop over pinned PageIndex segments that returns ledger-validated, exact-range citations.
---

# PageIndex Agentic Retrieval and Citations

## Purpose
<!-- FILL IN: stage 1 vs stage 2; when to use agentic_retrieve vs retrieve -->

## Public API
- [`PageIndexToolkit.agentic_retrieve`](ref:parrot.knowledge.pageindex.toolkit.PageIndexToolkit.agentic_retrieve) — stage-1 search + bounded reading loop
<!-- FILL IN: one bullet per symbol listed in the Codebase Contract -->

## Configuration & Parameters
<!-- FILL IN: constructor kwargs table; per-call overrides; MCP opt-in (exclude: + llm:) -->

## Usage Examples
<!-- FILL IN: python example with agentic_retrieve and reading bundle["citations"] / ["rendered_citations"] -->

## Gotchas
<!-- FILL IN: provider support table; no_tool_calls; ledger vs cursors; reasons table; stopped precedence -->

## Related
- [PageIndex — Tree-Based RAG for Document Retrieval](pageindex.md)
- [PageIndex Segment Store](pageindex-segment-store.md) — revisions, read tools and cursors this builds on
- [PageIndex Local MCP](pageindex-local-mcp.md) — the `exclude:` opt-in
```

### Link edits (MODIFY)
```markdown
# wiki/knowledge/pageindex.md — AFTER `- [Segment Store](pageindex-segment-store.md)` (verified :26) — occurrences: 1
- [Agentic Retrieval and Citations](pageindex-agentic-retrieval.md)

# wiki/knowledge/pageindex-segment-store.md — append as the LAST bullet of `## Related` (verified :142) — occurrences: 1
- [PageIndex Agentic Retrieval and Citations](pageindex-agentic-retrieval.md) — stage-2 loop and citations over these reads

# wiki/knowledge/pageindex-local-mcp.md — FILL IN: :44 `exclude: []` -> `exclude: [pageindex_agentic_retrieve]`;
#   rewrite :81-83 to describe the shipped default and link pageindex-agentic-retrieval.md
```

### `test_agentic_docs.py` (CREATE)
```python
"""The PageIndex agentic-retrieval documentation is present and linked."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
PAGE = REPO / "wiki" / "knowledge" / "pageindex-agentic-retrieval.md"


def test_page_has_frontmatter_api_and_reasons() -> None:
    text = PAGE.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: ")
    assert "\nsummary: " in text
    for name in (
        "ReadLedger", "validate_citations", "EvidenceBundle", "agentic_retrieve", "clone_for_tools",
        "bad_address", "revision_unread", "revision_unavailable", "segment_unread", "empty_excerpt",
        "excerpt_not_found", "outside_covered_ranges", "no_tool_calls", "max_tool_calls", "parse_error",
    ):
        assert name in text


def test_related_pages_link_new_page() -> None:
    for page in ("pageindex.md", "pageindex-segment-store.md", "pageindex-local-mcp.md"):
        text = (REPO / "wiki" / "knowledge" / page).read_text(encoding="utf-8")
        assert "pageindex-agentic-retrieval.md" in text
```

### FILL IN checklist
- [ ] page sections
- [ ] local-mcp page update

---

## Acceptance Criteria

- [ ] AC-15 page exists, is linked, and the techwiki check passes.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_agentic_docs.py -q`

---

## Test Specification

Spec §4 row `test_agentic_docs.py`.

---

## Agent Instructions

1. Run the validation command, then the techwiki gate from the repo root (AC-15; not a test-runner command):
   `parrot sdd techwiki check --spec sdd/specs/pageindex-agentic-retrieval.spec.md --root .`
2. Commit: `docs(pageindex-agentic-retrieval): TASK-5327 — agentic retrieval wiki page`.

---

## Completion Note

*(Agent fills this in when done)*
