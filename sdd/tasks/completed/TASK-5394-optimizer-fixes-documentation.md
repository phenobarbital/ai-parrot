# TASK-5394: Documentation — wiki/knowledge/pageindex-tree-optimizer.md

**Feature**: FEAT-853 — PageIndex Optimizer Fixes
**Spec**: `sdd/specs/pageindex-optimizer-fixes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5391, TASK-5392, TASK-5393
**Assigned-to**: unassigned

---

## Context

Spec §10 and Module 4. The docs policy is `required`. The optimizer page must describe the
behaviour this feature changed, so a reader of the page, or an agent reading it through the
wiki, does not expect the FEAT-846 behaviour:
- an empty leaf is no longer dropped silently;
- key items move with ownership;
- headings are inferred from bold/caps lines;
- prompts are bounded and windowed;
- `llm_calls_made` counts issued calls only.

---

## Scope

Update `wiki/knowledge/pageindex-tree-optimizer.md`:
- **"The passes, in order"**:
  - Normalize: an empty leaf becomes a parent alias (merge reason `empty`); a published empty
    leaf without a `concept_id` is kept. The absorber's span is widened over absorbed ranges.
  - Expand: the pseudo-heading fallback — standalone bold or upper-case lines, repeat filter
    (`PSEUDO_HEADING_MAX_REPEATS`), split-point coalescing. It only applies to leaves with no
    heading segment.
  - Heading pass: candidates only, plus the `is_heading_text` rule behind `heading_like`.
  - Key-item re-homing: `split_at`, `reconcile_key_items`, `key_items_rehomed`, drops counted in
    `rejected_proposals`.
- **"Framing"**: `LLM_INPUT_BUDGET_TOKENS`, windowing per pass, the summary reduce call, and the
  bounded `compose_parent`.
- **"### The report"**: add `key_items_rehomed`; state that `llm_calls_made` counts adapter calls
  actually issued (retry-cache hits excluded) and that `llm_calls_estimated` counts windows.

Extend `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py` so the page is
asserted to name `LLM_INPUT_BUDGET_TOKENS`, `key_items_rehomed`, `reconcile_key_items`,
`is_heading_text`, `pseudo_heading_segments` and `PSEUDO_HEADING_MAX_REPEATS`.

**NOT in scope**: code changes; other wiki pages; the evaluation tables recorded by `d2d7fc5bbf`
(leave them as they are).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/pageindex-tree-optimizer.md` | MODIFY | Document spec §2 A–E |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py` | MODIFY | Assert the new names |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# test_optimizer_docs.py (verified: test_optimizer_docs.py:1-10)
from pathlib import Path
from parrot.knowledge.pageindex.optimizer import OptimizerSettings
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py
REPO = Path(__file__).resolve().parents[5]          # line 7
PAGE = WIKI / "pageindex-tree-optimizer.md"          # line 9
def test_optimizer_page_exists_and_names_settings_and_commands() -> None:  # line 12 — `for name in (...)` tuple
def test_pages_link_optimizer_page() -> None:        # line 35

# wiki/knowledge/pageindex-tree-optimizer.md (re-verified at 9712eab0bb, after d2d7fc5bbf)
## The passes, in order     # line 46
### The report              # line 147 (an h3 under Configuration & Parameters)
## Framing                  # line 221
```
Symbol names to document (created by TASK-5391/5392/5393): `reconcile_key_items`,
`OptimizeReport.key_items_rehomed`, `is_heading_text`, `pseudo_heading_segments`,
`PSEUDO_HEADING_MAX_REPEATS` (`packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py`);
`LLM_INPUT_BUDGET_TOKENS`, `window_reads`
(`packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py`). Read both files (read-only)
before writing the page.

### Does NOT Exist
- ~~`OptimizerSettings.llm_input_tokens`~~ — no new setting. The existing docs test iterates
  `OptimizerSettings.model_fields`, so documenting a non-existent field would mislead.
- ~~`parrot sdd techwiki check` as a Validation Command~~ — not a registered runner; it stays in
  the acceptance criteria only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/knowledge/pageindex-tree-optimizer.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Read the final code of TASK-5391…5393 and the current page — *why*: document the merged
   names, not the spec's intent.
2. Edit the three page sections — *why*: §10 lists exactly these.
3. Extend the docs test, run it, run `parrot sdd techwiki check` — *why*: AC-13.

### `wiki/knowledge/pageindex-tree-optimizer.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^## The passes, in order' pageindex-tree-optimizer.md) -->
<!-- EDIT the Normalize / Expand / heading-pass / key-items items under `## The passes, in order` (line 46) -->
<!-- FILL IN: prose per Scope — bounded by AC-13; keep the frontmatter `title:` / `summary:` lines intact -->
<!-- occurrences: 1 (verified: grep -c '^## Framing' pageindex-tree-optimizer.md) -->
<!-- APPEND a "Bounded prompts" paragraph to `## Framing` (line 221) -->
```

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_pages_link_optimizer_page() -> None:' test_optimizer_docs.py)
# BEFORE — insert above `def test_pages_link_optimizer_page() -> None:` (verified: test_optimizer_docs.py:35)
def test_optimizer_page_documents_feat_853_fixes() -> None:
    """The optimizer page names the FEAT-853 behaviour: bounded prompts, re-homed anchors, pseudo-headings."""
    text = PAGE.read_text(encoding="utf-8")
    for name in (
        "LLM_INPUT_BUDGET_TOKENS",
        "key_items_rehomed",
        "reconcile_key_items",
        "is_heading_text",
        "pseudo_heading_segments",
        "PSEUDO_HEADING_MAX_REPEATS",
    ):
        assert name in text, name
```

### FILL IN checklist
- [ ] Page prose for the three sections; AC-13

---

## Acceptance Criteria

- [ ] AC-13: the page documents spec §2 A–E; `test_optimizer_docs.py` passes (old and new tests).
- [ ] `parrot sdd techwiki check --spec sdd/specs/pageindex-optimizer-fixes.spec.md --root .`
  reports no missing page.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py -q`

---

## Test Specification

See the blueprint test above. It must pass together with the existing
`test_optimizer_page_exists_and_names_settings_and_commands`.

---

## Agent Instructions

1. Work in the feature worktree; TASK-5391…5393 must be `done`.
2. Mark `in-progress`; edit; run the Validation Commands.
3. Commit only the two files; close with
   `parrot sdd task close TASK-5394 pageindex-optimizer-fixes verified`; fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude (Opus 5.5) — /sdd-fix session, actor agent:sdd-fix:5b4f798e
**Date**: 2026-11-09
**Notes**: Updated `wiki/knowledge/pageindex-tree-optimizer.md`: Purpose bullets; Public API (+ `reconcile_key_items`,
`is_heading_text`, `pseudo_heading_segments`, `window_reads`); "The passes, in order" (empty-leaf parent alias, span
widening, pseudo-heading fallback, candidate-only heading pass with the `is_heading_text` rule, windowed key items,
new step 7 "Re-home key items", renumbered summary/validate); "The report" (`key_items_rehomed`, `llm_calls_made` /
`llm_calls_estimated` semantics); Summaries (map-reduce, bounded composition); Framing ("Bounded prompts"); Aliases.
The evaluation tables recorded by d2d7fc5bbf are untouched. `test_optimizer_page_documents_feat_853_fixes` added
(also asserts `window_reads`). Validation: test_optimizer_docs — 3 passed; `parrot sdd techwiki check` — ok.

**Deviations from spec**: none.
