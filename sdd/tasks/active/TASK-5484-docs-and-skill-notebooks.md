# TASK-5484: Documentation — bookstore-notebooks, pageindex-local-mcp, bookstore-graph + skill funnel

**Feature**: FEAT-876 — Bookstore notebooks over a shared PageIndex
**Spec**: `sdd/specs/bookstore-notebooks-shared-pageindex.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5478, TASK-5482, TASK-5483
**Assigned-to**: unassigned

---

## Context

Implements spec **Module 9** and §10 (docs policy `required`). Documents the shipped behaviour of
TASK-5475..5483 and moves the research funnel's first step to `bookstore_find_books` in every skill copy, plus the
notebook citation rule. Runs last: it documents symbols the other tasks create.

---

## Scope

- Create `wiki/knowledge/bookstore-notebooks.md` from `sdd/templates/techwiki-page.md`: notebooks (per book / per
  library), anchors and `anchor_status`, sectors and two-step `find_books`, drafting, relation sheets,
  `add --import`, the write-policy table, the `pageindex-library` server, degraded modes (no LLM, no `bm25s`).
- Update `wiki/knowledge/pageindex-local-mcp.md` (under `## Gotchas`): `write_tools` / `read_only`, the
  `pageindex-library` template, "pointing the plain `pageindex` template at a library is unsupported for writes —
  use `pageindex-library`" (§8 Q2 resolution).
- Update `wiki/knowledge/bookstore-graph.md` (under `## Relation types and their determinism`): `origin="manual"`
  edges from relation sheets, `bookstore relate --from-notes`, survival across re-index and `relate --all`.
- Skill copies — tracked ones only: `.agent/skills/bookstore/SKILL.md`, `.agents/skills/bookstore/SKILL.md`,
  `.claude/commands/bookstore.md`, `packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore_assets.py`
  (`BOOKSTORE_SKILL`). Step 1 becomes `bookstore_find_books`, `bookstore_catalog_search` becomes the fallback;
  add the rule: "Annotations returned next to a section are the reader's notes — cite them as *Notebook:
  <title>*, never as book pages."
- `test_skill_text.py`: add mirrored constants for the new step-1 sentence and the notebook rule and assert them in
  the three files the test already compares; keep `FUNNEL_STEP_1B` / `CITATION_RULE` passing (if 1b's wording
  must change, change all three copies and the constant together).

**NOT in scope**: code changes. `.claude/skills/bookstore/SKILL.md` is **not tracked** in this repo
(`.git/info/exclude`) — do not `git add -f` it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/bookstore-notebooks.md` | CREATE | Feature page |
| `wiki/knowledge/pageindex-local-mcp.md` | MODIFY | Write policy + library template |
| `wiki/knowledge/bookstore-graph.md` | MODIFY | Manual edges |
| `.agent/skills/bookstore/SKILL.md` | MODIFY | Funnel step 1 + notebook rule |
| `.agents/skills/bookstore/SKILL.md` | MODIFY | Funnel step 1 + notebook rule |
| `.claude/commands/bookstore.md` | MODIFY | Funnel step 1 + notebook rule |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore_assets.py` | MODIFY | `BOOKSTORE_SKILL` mirror |
| `packages/ai-parrot/tests/knowledge/bookstore/test_skill_text.py` | MODIFY | Mirror constants |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` at task-writing time (2026-11-11). Use these exact names.
> If you need anything not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.knowledge.wiki.google.bookstore_assets import BOOKSTORE_SKILL   # verified: test_skill_text.py:41
```

### Existing Signatures to Use
```python
# Anchors (verified 2026-11-11, 1 occurrence each):
# .agent/skills/bookstore/SKILL.md:23     1. **`bookstore_catalog_search(query)`** — ALWAYS start here. Lexical
# .agent/skills/bookstore/SKILL.md:27     1b. **Expand by relations** — ...
# .agents/skills/bookstore/SKILL.md:12    ## Choose books, search sections, read evidence   (step 1 at :14)
# .claude/commands/bookstore.md:16        1. `bookstore_catalog_search` with the question's key topics — pick the
# .claude/commands/bookstore.md:18        1b. **Expand by relations** — ...
# bookstore_assets.py:16                  1. Start with `bookstore_catalog_search(query, top_k=8)` using topic keywords.
# wiki/knowledge/pageindex-local-mcp.md:109  ## Gotchas
# wiki/knowledge/bookstore-graph.md:19       ## Relation types and their determinism
# test_skill_text.py: FUNNEL_STEP_1B, CITATION_RULE constants; test_skill_mirrors_share_funnel_section compares
#   .agent/skills/bookstore/SKILL.md, .claude/commands/bookstore.md, BOOKSTORE_SKILL
```

### Does NOT Exist
- ~~`wiki/knowledge/bookstore.md`~~ — does not exist; Bookstore pages are `bookstore-graph.md`,
  `bookstore-agentic-retrieval.md`, `bookstore-codex.md` (+ the new `bookstore-notebooks.md`).
- ~~a tracked `.claude/skills/bookstore/SKILL.md`~~ — local-only file, excluded via `.git/info/exclude`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/knowledge/bookstore-notebooks.md",
      "action": "CREATE"
    },
    {
      "path": "wiki/knowledge/pageindex-local-mcp.md",
      "action": "MODIFY"
    },
    {
      "path": "wiki/knowledge/bookstore-graph.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/skills/bookstore/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/bookstore/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/bookstore.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore_assets.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_skill_text.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore_assets.py#BOOKSTORE_SKILL"
  ]
}
```

---

## Implementation Notes

- Describe only what TASK-5475..5483 shipped — read the merged code, not the spec, for names and flags.
- `FUNNEL_STEP_1B` mentions `bookstore_catalog_search` ("on the best `bookstore_catalog_search` hit"); keep it
  valid by leaving 1b untouched unless all three copies + the constant change together.
- `parrot sdd techwiki check --spec <spec> --root .` must pass (page frontmatter `title`/`summary`).

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Write the new wiki page; update the two existing pages — *why*: docs policy `required`.
2. Update the four tracked skill copies identically for the mirrored strings — *why*: agents start at `find_books`.
3. Extend `test_skill_text.py`; run it and the techwiki check.

### `wiki/knowledge/bookstore-notebooks.md` (CREATE)
```markdown
---
title: Bookstore notebooks
summary: Per-book and per-library notebooks over the Bookstore's PageIndex trees — anchors, sectors, find_books, relation sheets, tree import and the pageindex-library server.
---

# Bookstore notebooks

## Purpose
<!-- FILL IN: "the book is evidence, the notebook is yours"; when to use each tree kind -->

## Public API
<!-- FILL IN: Bookstore.notebook_for / library_notebook / ensure_notebook / annotations_for / remap_anchors /
     find_books / import_tree; notebooks.draft_* / relation_sheets; LibraryPageIndexToolkit -->

## Write policy
| Target tree | Structural ops | Node ops |
|---|---|---|
| catalogued `kind=book` | denied | denied |
| catalogued `kind=notes` | `rename_tree` / `delete_tree` denied; the rest allowed | allowed |
| not in the catalog | allowed | allowed |

<!-- FILL IN: remaining sections from sdd/templates/techwiki-page.md (anchors & anchor_status, sectors & find_books,
     drafting, relation sheets, add --import, degraded modes, gotchas incl. "plain pageindex template is unsupported") -->
```
### Skill copies (MODIFY ×4)
```markdown
<!-- Replace step 1 in each copy with the SAME sentence (it becomes a mirrored constant), e.g.:
1. **`bookstore_find_books(query)`** — ALWAYS start here. It answers "which books treat X, and where" from the
   librarian's sectors, with direct table-of-contents pointers; it falls back to `bookstore_catalog_search`.
and add, next to CITATION_RULE in each copy:
Annotations returned next to a section are the reader's notes — cite them as *Notebook: <title>*, never as book pages.
FILL IN: adapt surrounding prose per copy; keep the mirrored strings byte-identical -->
```

### FILL IN checklist
- [ ] New page sections — bounded by §10 bullet list
- [ ] Two page updates — bounded by §10
- [ ] Four skill copies with identical mirrored strings — bounded by AC-2
- [ ] `test_skill_text.py` constants + assertions — bounded by AC-2

---

## Acceptance Criteria

- [ ] AC-1: the three pages exist/are updated and `parrot sdd techwiki check --spec sdd/specs/bookstore-notebooks-shared-pageindex.spec.md --root .` passes.
- [ ] AC-2: every tracked skill copy starts the funnel with `bookstore_find_books` and carries the notebook citation rule; `test_skill_text.py` asserts both and still passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_skill_text.py -q`

---

## Test Specification

```python
# test_skill_text.py additions
FUNNEL_STEP_1 = "<the exact new step-1 text>"
NOTEBOOK_RULE = "Annotations returned next to a section are the reader's notes — cite them as *Notebook: <title>*, never as book pages."
def test_skill_text_funnel_starts_with_find_books(): ...   # all three compared copies + .agents/skills/bookstore/SKILL.md
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug bookstore-notebooks-shared-pageindex --feature-id FEAT-876`).
   Run tests with an absolute `PYTHONPATH=<worktree>/packages/ai-parrot/src`.
2. **Read the spec** at the path above (§2 Overview, the module section named in Context, §6, §7).
3. **Check dependencies** — every `Depends-on` task must be `done` in
   `sdd/tasks/index/bookstore-notebooks-shared-pageindex.json`.
4. **Verify the Codebase Contract** before writing code; if an entry is stale, fix the contract here first.
   Never use anything under "Does NOT Exist".
5. **Update status** in the per-spec index → `in-progress` (set `started_at`) and commit only that file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path.
7. **Validate**: `ruff check --fix <files>` and the Validation Commands below.
8. **Commit the code** — stage only the files listed in this task.
9. **Close** with `parrot sdd task close TASK-5484 bookstore-notebooks-shared-pageindex verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
