---
type: Wiki Overview
title: 'TASK-1328: Move pageindex package directory and rewrite internal references'
id: doc:sdd-tasks-completed-task-1328-move-pageindex-package-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The PageIndex subsystem lives at `packages/ai-parrot/src/parrot/pageindex/`
  and must move to `packages/ai-parrot/src/parrot/knowledge/pageindex/` so it sits
  alongside `parrot.knowledge.graphindex`. This is the foundation task — all subsequent
  tasks in FEAT-198 depend on it. Imple
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot._imports
  rel: mentions
- concept: mod:parrot.clients.base
  rel: mentions
- concept: mod:parrot.knowledge
  rel: mentions
- concept: mod:parrot.knowledge.graphindex
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.extractors.loader
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.knowledge.pageindex
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.navigator.prompt
  rel: mentions
---

# TASK-1328: Move pageindex package directory and rewrite internal references

**Feature**: FEAT-198 — move-pageindex-kb
**Spec**: `sdd/specs/move-pageindex-kb.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The PageIndex subsystem lives at `packages/ai-parrot/src/parrot/pageindex/` and must move to `packages/ai-parrot/src/parrot/knowledge/pageindex/` so it sits alongside `parrot.knowledge.graphindex`. This is the foundation task — all subsequent tasks in FEAT-198 depend on it. Implements §3 Module 1 of the spec.

After this task lands, the repo will be **briefly broken**: external importers (in graphindex, parrot_tools, examples, docs, tests) still reference `parrot.pageindex`. TASK-1329 / TASK-1330 / TASK-1331 fix that. Do **not** run the full test suite at the end of this task — only the package import smoke check. The grep-zero verification belongs to TASK-1332.

---

## Scope

- `git mv` all 15 source files from `packages/ai-parrot/src/parrot/pageindex/` to `packages/ai-parrot/src/parrot/knowledge/pageindex/` so Git tracks the rename and preserves blame.
- Inside each moved file: rewrite `logging.getLogger("parrot.pageindex")` (11 sites — see Codebase Contract below) to `logging.getLogger("parrot.knowledge.pageindex")`.
- Inside each moved file: rewrite docstring references of the form `parrot.pageindex.X.Y` to `parrot.knowledge.pageindex.X.Y`. Known sites: `ingest.py` lines 9–10, `pdf_to_markdown.py` lines 5, 7, 104.
- Delete the empty `packages/ai-parrot/src/parrot/pageindex/` directory (including `__pycache__/`) and confirm `git status` shows the rename.
- Do **not** edit relative imports (`from .schemas import …`) — they resolve correctly at the new location.
- Do **not** change `PageIndexToolkit.name = "pageindex"` or `tool_prefix = "pageindex"` (toolkit.py lines 74–75) — these are user-facing identifiers.
- Do **not** create a shim `__init__.py` at the old path. The old `parrot.pageindex` package must be unimportable after this task.

**NOT in scope** (covered by other tasks):
- Rewriting `from parrot.pageindex…` in `parrot.knowledge.graphindex.builder`, `parrot.knowledge.graphindex.extractors.loader`, or `parrot_tools.navigator.prompt` → TASK-1329.
- Moving / rewriting test files → TASK-1330.
- Updating `examples/` and `docs/pageindex.md` → TASK-1331.
- Repo-wide grep verification and lint → TASK-1332.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py` | CREATE (via `git mv` from old) | Package init; preserves relative imports |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py` | CREATE (via `git mv`) | Logger string rewrite at line 51 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py` | CREATE (via `git mv`) | Logger string rewrite at line 31 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` | CREATE (via `git mv`) | Logger string rewrite at line 28 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/ingest.py` | CREATE (via `git mv`) | Logger line 28 + docstring lines 9, 10 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py` | CREATE (via `git mv`) | Logger string rewrite at line 12 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py` | CREATE (via `git mv`) | Logger string rewrite at line 18 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py` | CREATE (via `git mv`) | Logger line 32 + docstring lines 5, 7, 104 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/prompts.py` | CREATE (via `git mv`) | No edits needed |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/retriever.py` | CREATE (via `git mv`) | `self.logger` string rewrite at line 36 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py` | CREATE (via `git mv`) | No edits needed |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/store.py` | CREATE (via `git mv`) | Logger string rewrite at line 18 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | CREATE (via `git mv`) | Logger line 45; **do NOT touch** `name`/`tool_prefix` lines 74–75 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/tree_ops.py` | CREATE (via `git mv`) | No edits needed |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py` | CREATE (via `git mv`) | Logger string rewrite at line 28 |
| `packages/ai-parrot/src/parrot/pageindex/` | DELETE | Entire directory + `__pycache__/` after move |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (current — referenced for context only)

```python
# packages/ai-parrot/src/parrot/pageindex/__init__.py:6-21
from .schemas import PageIndexNode, TreeSearchResult, TocItem
from .builder import build_page_index
from .md_builder import md_to_tree
from .retriever import PageIndexRetriever
from .llm_adapter import PageIndexLLMAdapter
from .store import JSONTreeStore
from .content_store import NodeContentStore
from .pdf_to_markdown import extract_markdown_per_page
from .tree_ops import splice_subtree, delete_node, reindex_node_ids
from .hybrid_search import HybridPageIndexSearch
from .ingest import TwoStepIngester, IngestedMarkdown
from .toolkit import PageIndexToolkit
```
These relative imports are correct AT THE NEW LOCATION too. Do not edit them.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):
    name = "pageindex"           # line 74 — DO NOT CHANGE (user-facing)
    tool_prefix = "pageindex"    # line 75 — DO NOT CHANGE (user-facing)
    # logger = logging.getLogger("parrot.pageindex") at line 45 → rewrite to "parrot.knowledge.pageindex"
```

### Logger sites to rewrite (11 total, verified)

```python
# Each of these uses logging.getLogger("parrot.pageindex"). After move, rewrite to "parrot.knowledge.pageindex".
parrot/pageindex/builder.py:51         logger = logging.getLogger("parrot.pageindex")
parrot/pageindex/content_store.py:31   logger = logging.getLogger("parrot.pageindex")
parrot/pageindex/hybrid_search.py:28   logger = logging.getLogger("parrot.pageindex")
parrot/pageindex/ingest.py:28          logger = logging.getLogger("parrot.pageindex")
parrot/pageindex/llm_adapter.py:12     logger = logging.getLogger("parrot.pageindex")
parrot/pageindex/md_builder.py:18      logger = logging.getLogger("parrot.pageindex")
parrot/pageindex/pdf_to_markdown.py:32 logger = logging.getLogger("parrot.pageindex")
parrot/pageindex/retriever.py:36       self.logger = logging.getLogger("parrot.pageindex")
parrot/pageindex/store.py:18           logger = logging.getLogger("parrot.pageindex")
parrot/pageindex/toolkit.py:45         logger = logging.getLogger("parrot.pageindex")
parrot/pageindex/utils.py:28           logger = logging.getLogger("parrot.pageindex")
```

### Docstring path sites to rewrite

```text
parrot/pageindex/ingest.py:9   :func:`parrot.pageindex.md_builder.md_to_tree`
parrot/pageindex/ingest.py:10  :func:`parrot.pageindex.tree_ops.splice_subtree`
parrot/pageindex/pdf_to_markdown.py:5    :func:`parrot.pageindex.utils.get_page_tokens`
parrot/pageindex/pdf_to_markdown.py:7    :func:`parrot.pageindex.builder.build_page_index`
parrot/pageindex/pdf_to_markdown.py:104  :func:`parrot.pageindex.utils.add_node_text`
```

### Pattern reference

The sibling package `packages/ai-parrot/src/parrot/knowledge/graphindex/` follows the same layout PageIndex will adopt. Its `__init__.py` uses absolute imports of the form `from parrot.knowledge.graphindex.schema import …`. PageIndex's current `__init__.py` uses relative imports (`from .schemas import …`) — preserve that style; do **not** rewrite to absolute paths.

### Does NOT Exist

- ~~`parrot/pageindex/` (after this task)~~ — directory is deleted; importing `parrot.pageindex` must fail with `ModuleNotFoundError`.
- ~~`parrot/knowledge/pageindex/shim.py` / `compat.py`~~ — no shim module is created.
- ~~`parrot.knowledge.__init__.py` re-exports of PageIndex symbols~~ — `parrot/knowledge/__init__.py` stays as it is (just the module docstring). FEAT-198 explicitly rejects top-level re-exports.
- ~~A `__getattr__` redirect in `parrot/__init__.py`~~ — explicitly forbidden by spec §1 Non-Goals.

---

## Implementation Notes

### Procedure

```bash
# 1. Move the package with git mv (preserves history per file)
mkdir -p packages/ai-parrot/src/parrot/knowledge/pageindex
git mv packages/ai-parrot/src/parrot/pageindex/*.py \
       packages/ai-parrot/src/parrot/knowledge/pageindex/

# 2. Rewrite logger strings (11 sites) — sed or Edit tool
#    Replace "parrot.pageindex" with "parrot.knowledge.pageindex" ONLY in the
#    moved files, and only inside getLogger() calls and the listed docstring
#    sites. Do NOT do a blind project-wide sed — other importers are out of
#    scope here.

# 3. Verify the old directory is gone
test ! -d packages/ai-parrot/src/parrot/pageindex && echo "removed"

# 4. Smoke import (FROM THE NEW PATH ONLY — external callers still broken)
source .venv/bin/activate
python -c "from parrot.knowledge.pageindex import PageIndexToolkit; print('ok')"
```

### Edit-by-edit safety

- Prefer the `Edit` tool with `replace_all=False` and a unique `old_string` that includes 1–2 surrounding lines, to avoid accidentally rewriting any string that should stay (e.g. the `name = "pageindex"` literal).
- Do **not** use a sweeping `sed -i` over the moved directory unless you're certain there are no `"pageindex"` literals that must stay (toolkit name, tool_prefix, comments referring to the subsystem by name).

### Key Constraints

- Async-first project — no behavioral edits, this is pure relocation.
- Preserve every byte of logic. Only logger strings, docstring path refs, and the directory location change.
- Do not regenerate `build/lib.*/` artifacts — they will be regenerated next install.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py` — pattern for a knowledge subsystem package (uses absolute imports; PageIndex preserves its relative-import style).
- `packages/ai-parrot/src/parrot/knowledge/__init__.py` — confirms the parent namespace is empty (just a docstring). Don't add re-exports.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/pageindex/` does NOT exist (`test ! -d` returns true).
- [ ] `packages/ai-parrot/src/parrot/pageindex` does NOT appear in `git ls-files`.
- [ ] `packages/ai-parrot/src/parrot/knowledge/pageindex/` exists with the 15 source files from the Files table.
- [ ] `git log --follow packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py` shows pre-move history (rename detected).
- [ ] `grep -n 'logging.getLogger(\"parrot.pageindex\")' packages/ai-parrot/src/parrot/knowledge/pageindex/*.py` returns ZERO matches.
- [ ] `grep -n 'logging.getLogger(\"parrot.knowledge.pageindex\")' packages/ai-parrot/src/parrot/knowledge/pageindex/*.py` returns exactly the 11 expected sites.
- [ ] `grep -rn 'parrot\\.pageindex\\.' packages/ai-parrot/src/parrot/knowledge/pageindex/` returns ZERO matches (docstrings are rewritten too).
- [ ] `PageIndexToolkit.name == "pageindex"` and `tool_prefix == "pageindex"` are unchanged. Verify via grep: `grep -n 'name = \"pageindex\"\\|tool_prefix = \"pageindex\"' packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` shows lines 74 and 75 (or thereabouts post-rewrite).
- [ ] `python -c "from parrot.knowledge.pageindex import PageIndexToolkit, PageIndexRetriever, PageIndexLLMAdapter, build_page_index, md_to_tree, HybridPageIndexSearch, JSONTreeStore, NodeContentStore, TwoStepIngester, IngestedMarkdown"` prints nothing (succeeds).
- [ ] `python -c "import parrot.pageindex"` raises `ModuleNotFoundError`.

---

## Test Specification

This task is verified by import smoke checks; no behavioral tests run yet (the wider suite is broken until TASK-1330 lands).

```bash
source .venv/bin/activate

# Must succeed
python -c "
from parrot.knowledge.pageindex import (
    PageIndexToolkit, PageIndexRetriever, PageIndexLLMAdapter,
    build_page_index, md_to_tree, HybridPageIndexSearch,
    JSONTreeStore, NodeContentStore, TwoStepIngester, IngestedMarkdown,
    PageIndexNode, TreeSearchResult, TocItem,
)
print('imports ok')
"

# Must fail
python -c "import parrot.pageindex" 2>&1 | grep -q ModuleNotFoundError && echo "old path gone"
```

Do NOT run `pytest packages/ai-parrot/tests/test_pageindex/` here — those tests still reference the old path and will fail. TASK-1330 fixes them.

---

### Completion Note

Completed by sdd-worker 2026-05-28.

All 15 files moved via `git mv` preserving blame history. Logger strings rewritten at 11 sites (10 module-level `logging.getLogger("parrot.pageindex")` + 1 instance-level in `retriever.py`). Docstring path refs rewritten in `ingest.py` (lines 9-10) and `pdf_to_markdown.py` (lines 5, 7, 104). `PageIndexToolkit.name` and `tool_prefix` left as `"pageindex"` (user-facing identifiers, unchanged).

Contract update: the spec's "Internal relative imports require no edits" applied to single-dot intra-package imports. Three files had double-dot (`..`) imports that changed meaning at the new package depth (`parrot.knowledge.pageindex` vs `parrot.pageindex`). These were converted to absolute imports:
- `llm_adapter.py`: `from ..clients.base` → `from parrot.clients.base`; `from ..models.outputs` → `from parrot.models.outputs`
- `hybrid_search.py`: `from .._imports` → `from parrot._imports`; lazy `from ..stores.models` → `from parrot.stores.models`
- `toolkit.py`: `from ..tools.toolkit` → `from parrot.tools.toolkit`

Import smoke check `from parrot.knowledge.pageindex import PageIndexToolkit, ...` passed (PYTHONPATH override on worktree src). Old path `import parrot.pageindex` still resolves from main repo's editable install namespace — will fail correctly once PR is merged to dev.
