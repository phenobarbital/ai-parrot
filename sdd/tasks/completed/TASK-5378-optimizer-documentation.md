# TASK-5378: Documentation — pageindex-tree-optimizer, pageindex, pageindex-local-mcp

**Feature**: FEAT-846 — PageIndex Tree Optimizer
**Spec**: `sdd/specs/pageindex-tree-optimizer.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5376, TASK-5374, TASK-5369, TASK-5377
**Assigned-to**: unassigned

---

## Context

Spec §10 (docs policy `required`), AC-2. Template: `sdd/templates/techwiki-page.md`.

## Scope

- Create `wiki/knowledge/pageindex-tree-optimizer.md` covering every bullet of spec §10 (incl. how the shipped
  `target_leaf_tokens` was set — report date + sha256 from TASK-5376's Completion Note, or "provisional").
- `pageindex.md` Configuration Options: `optimize_on_import`, `optimizer_settings`; API Reference link.
- `pageindex-local-mcp.md`: `pageindex_optimize` next to `pageindex_agentic_retrieve`, marked as working without `llm:`.
- `test_optimizer_docs.py` (pattern of `test_layout_docs.py`).

**NOT in scope**: code changes; any metrics table not copied from the TASK-5376 report.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/pageindex-tree-optimizer.md` | CREATE | new page (spec §10) |
| `wiki/knowledge/pageindex.md` | MODIFY | Configuration Options + API link |
| `wiki/knowledge/pageindex-local-mcp.md` | MODIFY | pageindex_optimize in tool list |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py` | CREATE | docs presence test |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```text
wiki/knowledge/pageindex.md:457           ## Configuration Options   (occurrences: 1)
wiki/knowledge/pageindex-local-mcp.md:68  - `pageindex_agentic_retrieve`   (occurrences: 1)
packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py — docs test pattern
sdd/templates/techwiki-page.md — page template (frontmatter: title, summary)
```

### Does NOT Exist
- ~~`wiki/knowledge/pageindex-tree-optimizer.md`~~ — new here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/knowledge/pageindex-tree-optimizer.md",
      "action": "CREATE"
    },
    {
      "path": "wiki/knowledge/pageindex.md",
      "action": "MODIFY"
    },
    {
      "path": "wiki/knowledge/pageindex-local-mcp.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Name both commands (`parrot pageindex optimize`, `bookstore optimize`) and every `OptimizerSettings` field — the docs
  test checks for them.

---

## Implementation Blueprint

### `wiki/knowledge/pageindex-tree-optimizer.md` (CREATE)
```markdown
---
title: PageIndex Tree Optimizer
summary: <FILL IN one sentence>
---

# PageIndex Tree Optimizer

<!-- FILL IN: one section per spec §10 bullet, from sdd/templates/techwiki-page.md -->
```

### `wiki/knowledge/pageindex.md` (MODIFY)
```markdown
<!-- AFTER `## Configuration Options` (:457; occurrences: 1): FILL IN rows/bullets for optimize_on_import, optimizer_settings -->
```

### `wiki/knowledge/pageindex-local-mcp.md` (MODIFY)
```markdown
<!-- AFTER `- `pageindex_agentic_retrieve`` (:68; occurrences: 1) -->
- `pageindex_optimize` — dry-run/apply the tree optimizer; works without `llm:` (deterministic passes and summaries)
```

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py` (CREATE)
```python
def test_optimizer_page_exists_and_names_settings_and_commands(): ...  # FILL IN (pattern of test_layout_docs.py)
```

---

## Acceptance Criteria

- [ ] AC-2: page exists; `parrot sdd techwiki check --spec sdd/specs/pageindex-tree-optimizer.spec.md --root .` passes.


## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py -q`

---

## Test Specification

Spec §4 row `test_optimizer_docs.py`.

---

## Agent Instructions

0. Also run `parrot sdd techwiki check --spec sdd/specs/pageindex-tree-optimizer.spec.md --root .` (AC-2; not a test runner).

1. Read the spec sections named in Context, then this task's Codebase Contract — use only the listed imports.
2. Re-run `grep -c` on every MODIFY anchor before editing; a count that differs from the blueprint means drift — stop and report.
3. Write the blueprint blocks, then resolve every `FILL IN` within its stated bound.
4. Run `ruff check --fix` on the touched files and the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the files listed above: `feat(pageindex-tree-optimizer): TASK-5378 — Documentation — pageindex-tree-optimizer, pageindex, pageindex-local-mcp`.

---

## Completion Note

**Completed**: 2026-11-09 | **Implementation commit**: 699ad11b68

Delivered via sdd-coder pool (merged). Scope: optimizer documentation (wiki pages + docs test); tuning explicitly marked pending, no metrics cited.
Validation: docs tests — passed (see run above); techwiki check reported by coder: ok.
Deviations: none noted.

