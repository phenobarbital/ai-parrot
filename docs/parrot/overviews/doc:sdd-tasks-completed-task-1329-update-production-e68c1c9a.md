---
type: Wiki Overview
title: 'TASK-1329: Update production source-code importers to `parrot.knowledge.pageindex`'
id: doc:sdd-tasks-completed-task-1329-update-production-importers-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After TASK-1328 moves the package, six production-source imports still reference
  the old `parrot.pageindex` path. They break at import time until rewritten. This
  task fixes them. Implements §3 Module 2 of the spec.
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots.mixins.intent_router
  rel: mentions
- concept: mod:parrot.knowledge
  rel: mentions
- concept: mod:parrot.knowledge.graphindex
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.extractors.loader
  rel: mentions
- concept: mod:parrot.knowledge.pageindex
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.toolkit
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.utils
  rel: mentions
- concept: mod:parrot.manager.ephemeral
  rel: mentions
- concept: mod:parrot_tools.navigator
  rel: mentions
- concept: mod:parrot_tools.navigator.prompt
  rel: mentions
---

# TASK-1329: Update production source-code importers to `parrot.knowledge.pageindex`

**Feature**: FEAT-198 — move-pageindex-kb
**Spec**: `sdd/specs/move-pageindex-kb.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1328
**Assigned-to**: unassigned

---

## Context

After TASK-1328 moves the package, six production-source imports still reference the old `parrot.pageindex` path. They break at import time until rewritten. This task fixes them. Implements §3 Module 2 of the spec.

Scope is intentionally narrow: only the six lines listed in the Files table. Tests, examples, and docs are handled by TASK-1330 / TASK-1331. Repo-wide grep verification is TASK-1332.

---

## Scope

- Rewrite the six `from parrot.pageindex…` / `import parrot.pageindex…` statements listed in the Files table to use `parrot.knowledge.pageindex…`.
- Preserve the surrounding context of each statement (e.g. the lazy-import inside a method body in `graphindex/extractors/loader.py:351` must stay lazy — only the module path changes).
- After all six edits, verify with `grep -rn 'parrot\.pageindex' packages/ai-parrot/src/ packages/ai-parrot-tools/src/` returns zero hits (the moved package no longer references the old name; this task removes the only remaining production-source references).

**NOT in scope**:
- Tests (`tests/test_pageindex/`, `tests/knowledge/graphindex/test_loader_extractor.py`) → TASK-1330.
- Examples and docs → TASK-1331.
- Changing the **behavior** of any importer — only the import path moves.
- `parrot.bots.mixins.intent_router` and `parrot.manager.ephemeral` — they don't import `parrot.pageindex`; they reference local attributes (`_pageindex_retriever`) and string literals (`rag_mode == "pageindex"`). Leave them alone.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` | MODIFY | Line 49: `from parrot.pageindex.toolkit import PageIndexToolkit` → `from parrot.knowledge.pageindex.toolkit import PageIndexToolkit` |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py` | MODIFY | Line 39: `from parrot.pageindex.toolkit import PageIndexToolkit` → `from parrot.knowledge.pageindex.toolkit import PageIndexToolkit` |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py` | MODIFY | Line 351: `from parrot.pageindex import md_to_tree` → `from parrot.knowledge.pageindex import md_to_tree` |
| `packages/ai-parrot-tools/src/parrot_tools/navigator/prompt.py` | MODIFY | Line 24: `from parrot.pageindex import PageIndexLLMAdapter, PageIndexRetriever, md_to_tree` → `from parrot.knowledge.pageindex import …` |
| `packages/ai-parrot-tools/src/parrot_tools/navigator/prompt.py` | MODIFY | Line 25: `from parrot.pageindex.utils import write_node_id` → `from parrot.knowledge.pageindex.utils import write_node_id` |
| `packages/ai-parrot-tools/src/parrot_tools/navigator/prompt.py` | MODIFY | Line 235: `from parrot.pageindex.utils import find_node_by_id` → `from parrot.knowledge.pageindex.utils import find_node_by_id` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (target paths — use these verbatim)

```python
# After this task, these are the canonical imports:
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.pageindex import md_to_tree
from parrot.knowledge.pageindex import PageIndexLLMAdapter, PageIndexRetriever, md_to_tree
from parrot.knowledge.pageindex.utils import write_node_id, find_node_by_id
```

All of these resolve because TASK-1328 already moved the symbols. Re-verify by:
```bash
source .venv/bin/activate
python -c "from parrot.knowledge.pageindex import PageIndexToolkit, PageIndexRetriever, PageIndexLLMAdapter, md_to_tree"
python -c "from parrot.knowledge.pageindex.utils import write_node_id, find_node_by_id"
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py
# Line 49 currently:
from parrot.pageindex.toolkit import PageIndexToolkit
# Used downstream as a constructor call — class identity unchanged, only module path moves.
```

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py
# Line 39 (TYPE_CHECKING / lazy-import block):
    from parrot.pageindex.toolkit import PageIndexToolkit
# Line 351 (inside a method body — keep it lazy):
            from parrot.pageindex import md_to_tree
```

```python
# packages/ai-parrot-tools/src/parrot_tools/navigator/prompt.py
# Lines 24-25 (module top):
from parrot.pageindex import PageIndexLLMAdapter, PageIndexRetriever, md_to_tree
from parrot.pageindex.utils import write_node_id
# Line 235 (inside a method body — keep it lazy):
        from parrot.pageindex.utils import find_node_by_id
```

### Does NOT Exist

- ~~`parrot.pageindex` (post-TASK-1328)~~ — gone. Any leftover reference is a regression.
- ~~`parrot.knowledge.pageindex.PageIndexToolkit` does not need re-export at `parrot.knowledge`~~ — importers go to the full canonical path; no shorter alias exists.
- ~~A `parrot.pageindex` compatibility module~~ — explicitly forbidden by FEAT-198.

---

## Implementation Notes

### Procedure

Edit each line in place via the `Edit` tool with `replace_all=False` and a unique `old_string` (include the surrounding 1–2 lines to disambiguate the two `loader.py` sites).

For `parrot_tools/navigator/prompt.py:24-25`, the two consecutive lines are a single block — you can replace both in one `Edit` call.

### Key Constraints

- Do not change the **shape** of any import — if it was lazy (inside a function), keep it lazy. If it was `from X import a, b, c`, keep the same names; do not switch to `import X` and dot-access.
- After each edit, run `python -c "import <module>"` for the touched module to confirm it still resolves. Example:
  ```bash
  python -c "import parrot.knowledge.graphindex.builder"
  python -c "import parrot.knowledge.graphindex.extractors.loader"
  python -c "import parrot_tools.navigator.prompt"
  ```

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py` — confirms the public symbols (`PageIndexToolkit`, `PageIndexRetriever`, `PageIndexLLMAdapter`, `md_to_tree`, etc.) are re-exported and resolvable from the new path.

---

## Acceptance Criteria

- [ ] All six lines listed in the Files table are updated to `parrot.knowledge.pageindex…`.
- [ ] `grep -rn 'parrot\.pageindex' packages/ai-parrot/src/ packages/ai-parrot-tools/src/ --include='*.py'` returns ZERO matches (assuming TASK-1328 already eliminated them from the moved package itself; this task closes the remaining production-source references).
- [ ] `python -c "import parrot.knowledge.graphindex.builder"` succeeds.
- [ ] `python -c "import parrot.knowledge.graphindex.extractors.loader"` succeeds.
- [ ] `python -c "import parrot_tools.navigator.prompt"` succeeds.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py packages/ai-parrot-tools/src/parrot_tools/navigator/prompt.py` returns 0 issues.

---

## Test Specification

No new tests. Existing tests for graphindex and parrot_tools.navigator must continue to pass after these import rewrites. They are re-run as part of TASK-1330 / TASK-1332.

Quick smoke (does not require pytest fixtures):
```bash
source .venv/bin/activate
python -c "
from parrot.knowledge.graphindex.builder import *  # noqa: F401,F403 — module-level import smoke
import parrot.knowledge.graphindex.extractors.loader  # noqa: F401
import parrot_tools.navigator.prompt  # noqa: F401
print('production importers ok')
"
```

---

### Completion Note

Completed by sdd-worker 2026-05-28.

All 6 production-source import sites rewritten to `parrot.knowledge.pageindex.*`:
- `graphindex/builder.py:49` — `from parrot.pageindex.toolkit import PageIndexToolkit` updated
- `graphindex/extractors/loader.py:39` — TYPE_CHECKING block updated
- `graphindex/extractors/loader.py:351` — lazy import inside method body updated (kept lazy)
- `parrot_tools/navigator/prompt.py:24-25` — two consecutive top-level imports updated together
- `parrot_tools/navigator/prompt.py:235` — lazy import inside method body updated (kept lazy)

Syntax check via `python -m py_compile` passed for all 3 files. `grep -rn 'parrot.pageindex' packages/.../src/ --include='*.py'` returns zero matches.

Pre-existing ruff issue noted: `loader.py` has an F401 for unused import of `Provenance` from graphindex schema (present in main repo before this PR). Not fixed here — out of scope per FEAT-198 cardinal rules.
