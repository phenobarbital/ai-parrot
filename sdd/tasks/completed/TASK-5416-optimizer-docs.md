# TASK-5416: Documentation — wiki/knowledge/pageindex-tree-optimizer.md

**Feature**: FEAT-857 — PageIndex Optimizer Fixes 2 — Page Fields and Footer-Safe Pseudo-Headings
**Spec**: `sdd/specs/pageindex-optimizer-fixes-2.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5415
**Assigned-to**: unassigned

**Discovered-from**: `issue:5396799daf67`
**Discovered-from**: `issue:38e4627b2284`

---

## Context

Spec §3 Module 2 and §10. Documents the page fields on expanded pieces and the `running_key` repeat rule that
TASK-5415 introduces.

---

## Scope

- Update step 4 ("Expand at headings") of `wiki/knowledge/pageindex-tree-optimizer.md`.
- Extend the names assertion in `test_optimizer_docs.py`.

**NOT in scope**: code changes; other wiki pages.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/pageindex-tree-optimizer.md` | MODIFY | page fields; `running_key` repeat rule |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py` | MODIFY | assert the new names |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pathlib import Path  # verified: test_optimizer_docs.py:3
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py
def test_optimizer_page_documents_feat_853_fixes() -> None   # names loop starts with "LLM_INPUT_BUDGET_TOKENS"
# wiki/knowledge/pageindex-tree-optimizer.md
#   "4. **Expand at headings.**" line 69; the pseudo-heading paragraph ends "...(the segmenter still types those lines `paragraph`)." ~line 80
#   `PSEUDO_HEADING_MAX_REPEATS` (2) mentioned at line 76
```

### Does NOT Exist
- ~~`_piece_pages` in the public API~~ — private helper; document the behaviour, not a link to it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/knowledge/pageindex-tree-optimizer.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py#test_optimizer_page_documents_feat_853_fixes"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Describe only what TASK-5415 implemented (read its final diff first).
- Names the test asserts must appear verbatim in the page: `running_key`, `start_index`, `end_index`.

---

## Implementation Blueprint

### Steps (in order)
1. Read the merged TASK-5415 code — because the page must match it.
2. Edit the wiki page — because spec §10 requires it.
3. Add the names to the docs test.

### `wiki/knowledge/pageindex-tree-optimizer.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c -F 'segment kinds are not changed (the segmenter still types those lines `paragraph`).' pageindex-tree-optimizer.md) — after that sentence, add: -->
<FILL IN: (a) repeat counts are keyed by `running_key` (casefold, digit runs → `#`), so a footer that differs only by
   its page number (`CHAPTER THREE PAGE 19`, `APPENDIX C PAGE 428`) counts as one repeated title and is ignored once it
   occurs more than `PSEUDO_HEADING_MAX_REPEATS` times; (b) pieces created from a paged revision carry `start_index`
   (page of the first owned segment) and `end_index` (page of the last owned segment); unpaged (ebook/markdown)
   pieces carry neither — bounded by spec §2 Overview>
```

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        "LLM_INPUT_BUDGET_TOKENS",' test_optimizer_docs.py)
# AFTER — insert below `        "LLM_INPUT_BUDGET_TOKENS",`
        "running_key",
        "start_index",
        "end_index",
```

### FILL IN checklist
- [ ] the wiki paragraph (a) and (b)

---

## Acceptance Criteria

- [ ] The page describes the `running_key` repeat rule and the piece page fields.
- [ ] `parrot sdd techwiki check --spec sdd/specs/pageindex-optimizer-fixes-2.spec.md --root .` passes.
- [ ] `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py -q` passes.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py -q`

---

## Test Specification

```python
# test_optimizer_docs.py — extend the names tuple only (see blueprint); no new test functions
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `base_branch`
2. **Check dependencies** — TASK-5415 must be `"done"` in `sdd/tasks/index/pageindex-optimizer-fixes-2.json`
3. **Update status** in the per-spec index → `"in-progress"`; commit only that file
4. **Implement**, completing the `FILL IN`
5. **Verify** with `PYTHONPATH=packages/ai-parrot/src`
6. **Commit** only the files this task lists
7. **Close** with `parrot sdd task close TASK-5416 pageindex-optimizer-fixes-2 verified`
8. Fill in the Completion Note, commit the SDD state

---

## Completion Note

**Completed by**: sdd-fix session (Claude)
**Date**: 2026-11-09
**Notes**: Documented the `running_key` repeat rule and piece page fields in step 4; docs test asserts `running_key`, `start_index`, `end_index`. `techwiki check` ok; docs test passes.

**Deviations from spec**: none
