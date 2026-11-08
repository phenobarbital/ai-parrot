# TASK-5289: Documentation — wiki/knowledge/pageindex-generation-publication.md

**Feature**: FEAT-831 — PageIndex Generation Publication
**Spec**: `sdd/specs/pageindex-generation-publication.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5287
**Assigned-to**: unassigned

---

## Context

Spec §10 (`docs.policy: required`). Documents the generation model for operators and integrators:
what a generation is, where bodies live, how locking and the stale check behave, the grace period
and sweep, how legacy trees migrate on their first write, the two toolkit kwargs and the two new tools.

---

## Scope

- Create `wiki/knowledge/pageindex-generation-publication.md` from `sdd/templates/techwiki-page.md`.
- Update `wiki/knowledge/pageindex.md`: link the new page from its table of contents and from
  "Configuration Options".
- Register the page in `wiki/_index.yaml` if `parrot sdd techwiki check` requires it (and then
  add `wiki/_index.yaml` to the Completion Note as a deviation — it is not in the Files table).
- Write `test_generation_docs.py`: the page exists, has `title`/`summary` frontmatter, names the
  public API and the two tools, and `pageindex.md` links it — *because* `parrot sdd techwiki check`
  is not a registered test runner, so a pytest file is the task's machine-checked validation
  (same pattern as TASK-5269).

**NOT in scope**: code changes; docstring edits outside the two API modules.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/pageindex-generation-publication.md` | CREATE | New page |
| `wiki/knowledge/pageindex.md` | MODIFY | Link the new page |
| `packages/ai-parrot/tests/knowledge/pageindex/test_generation_docs.py` | CREATE | Docs presence test |

---

## Codebase Contract (Anti-Hallucination)

### Existing references
```text
sdd/templates/techwiki-page.md                 # template: frontmatter (title, summary) + Purpose, Public API,
                                               #   Configuration & Parameters, Usage Examples …
wiki/knowledge/pageindex.md                    # "## Table of Contents" :14, "## Configuration Options" :436
```
Public names to document (after TASK-5276..5287): `GenerationInfo`, `StaleGenerationError`,
`TreeLockTimeout`, `WriteTransaction`, `tree_lock`, `PageIndexToolkit(generation_grace_s=, lock_timeout_s=)`,
tools `pageindex_get_generation`, `pageindex_vacuum_tree`; layout `<storage_dir>/<tree>.json`,
`<storage_dir>/<tree>/bodies/<flat_concept_id>.<sha16>.md`, `<storage_dir>/.locks/<tree>.lock`.

### Does NOT Exist
- ~~a generation manifest file~~ — do not document one; the tree JSON is the publication point

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/knowledge/pageindex-generation-publication.md",
      "action": "CREATE"
    },
    {
      "path": "wiki/knowledge/pageindex.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_generation_docs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- State plainly what readers get: the generation they loaded, for at least the grace period.
- Mention the eleven body readers that resolve through the live JSON (spec §2) as "live semantics".
- Keep examples runnable (`await toolkit.get_generation("tree")`).

---

## Implementation Blueprint

### Steps (in order)
1. Copy the template and fill each section from spec §2 Overview — *why*: the spec is the source of truth.
2. Link it from `pageindex.md`.
3. Run the docs check.

### `wiki/knowledge/pageindex-generation-publication.md` (CREATE)
```markdown
---
title: PageIndex Generation Publication
summary: How PageIndex trees are written as immutable generations — copy-on-write, cross-process lock, body blobs and the sweep.
---

# PageIndex Generation Publication

## Purpose
<!-- FILL IN: problem (lost updates, torn reads) and the guarantee readers get -->

## Public API
- [`GenerationInfo`](ref:parrot.knowledge.pageindex.generation.GenerationInfo) — generation id, timestamp, parent
- [`StaleGenerationError`](ref:parrot.knowledge.pageindex.generation.StaleGenerationError) — candidate built on an old generation
- [`TreeLockTimeout`](ref:parrot.knowledge.pageindex.locks.TreeLockTimeout) — lock not acquired in time

## Configuration & Parameters
<!-- FILL IN: generation_grace_s, lock_timeout_s, storage layout -->

## Usage Examples
<!-- FILL IN: get_generation, vacuum_tree, handling StaleGenerationError -->
```

### FILL IN checklist
- [ ] the four sections
- [ ] link from `pageindex.md`

---

## Acceptance Criteria

- [ ] AC-1: `parrot sdd techwiki check --spec sdd/specs/pageindex-generation-publication.spec.md --root .` passes (acceptance check; not a registered test runner).
- [ ] AC-2: `wiki/knowledge/pageindex.md` links the new page.
- [ ] AC-3: `test_generation_docs.py` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_generation_docs.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_generation_docs.py
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
PAGE = REPO / "wiki" / "knowledge" / "pageindex-generation-publication.md"


def test_page_has_frontmatter_and_api():
    text = PAGE.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: ")
    for name in ("GenerationInfo", "StaleGenerationError", "TreeLockTimeout",
                 "pageindex_get_generation", "pageindex_vacuum_tree", "generation_grace_s"):
        assert name in text


def test_pageindex_page_links_new_page():
    text = (REPO / "wiki" / "knowledge" / "pageindex.md").read_text(encoding="utf-8")
    assert "pageindex-generation-publication.md" in text
```
Also run (acceptance, not a registered test runner):
`parrot sdd techwiki check --spec sdd/specs/pageindex-generation-publication.spec.md --root .`

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-generation-publication --feature-id FEAT-831`).
   Run tests with `PYTHONPATH=packages/ai-parrot/src` — the shared venv is editable-installed
   against the main checkout.
2. **Read the spec** at the path listed above for full context (§2 Overview is the design).
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/pageindex-generation-publication.json`.
4. **Verify the Codebase Contract** before writing code: re-run the `grep -c` of every MODIFY
   anchor; a count of `0` means drift — stop and report, do not invent an attachment point.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file.
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
7. **Verify** — run the Validation Commands and `ruff check` on the files you touched.
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`).
9. **Close the task** with `parrot sdd task close TASK-5289 pageindex-generation-publication verified`.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
