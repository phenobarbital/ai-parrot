---
type: Wiki Overview
title: 'TASK-1331: Update examples and documentation imports'
id: doc:sdd-tasks-completed-task-1331-update-examples-and-docs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Five example scripts under `examples/` and the user-facing `docs/pageindex.md`
  reference the old `parrot.pageindex` import path. After TASK-1328 moves the package,
  these are stale — copy-paste failures for any user reading them. Implements §3 Module
  4 of the spec.
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.knowledge.pageindex
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.llm_adapter
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.retriever
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.utils
  rel: mentions
---

# TASK-1331: Update examples and documentation imports

**Feature**: FEAT-198 — move-pageindex-kb
**Spec**: `sdd/specs/move-pageindex-kb.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1328
**Assigned-to**: unassigned

---

## Context

Five example scripts under `examples/` and the user-facing `docs/pageindex.md` reference the old `parrot.pageindex` import path. After TASK-1328 moves the package, these are stale — copy-paste failures for any user reading them. Implements §3 Module 4 of the spec.

These changes are documentation-only — they do not affect runtime if examples aren't executed in CI. They DO affect anyone following the docs or running the example scripts.

---

## Scope

- Rewrite `parrot.pageindex` import statements in five example scripts (8 total references) to `parrot.knowledge.pageindex`.
- Rewrite nine import-snippet code blocks in `docs/pageindex.md` to use `parrot.knowledge.pageindex…`.
- Scan `docs/pageindex.md` for **non-code-block prose** mentioning `parrot.pageindex` (e.g. inline references in paragraphs) and update those too.
- Leave the `examples/pageindex/` directory name (and any other directory name) unchanged — directory layout is not Python module paths.

**NOT in scope**:
- Test files → TASK-1330.
- Production source importers → TASK-1329.
- Refactoring any example logic or expanding documentation.
- Generated docs site (`site/`) — that's a build artifact regenerated from `docs/`.
- Historical SDD documents (`sdd/tasks/completed/`, `sdd/proposals/`, prior `sdd/specs/*.spec.md`) — they document history and must remain unchanged.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/navigator_agent.py` | MODIFY | Line 21: `from parrot.pageindex import PageIndexLLMAdapter` → `from parrot.knowledge.pageindex import …` |
| `examples/shoply/sample.py` | MODIFY | Line 36: `from parrot.pageindex.retriever import PageIndexRetriever` |
| `examples/shoply/sample.py` | MODIFY | Line 37: `from parrot.pageindex.llm_adapter import PageIndexLLMAdapter` |
| `examples/graphindex/graphindex_corpus_agent.py` | MODIFY | Line 74: `from parrot.pageindex import PageIndexLLMAdapter, PageIndexToolkit` |
| `examples/pageindex/pageindex_compliance_agent.py` | MODIFY | Line 4 (module docstring): `:class:` ref to `parrot.pageindex.PageIndexToolkit` |
| `examples/pageindex/pageindex_compliance_agent.py` | MODIFY | Line 46: `from parrot.pageindex import (...)` |
| `examples/orchestrator/knowledge/ingest.py` | MODIFY | Line 49: `from parrot.pageindex import PageIndexLLMAdapter, PageIndexToolkit` (inside a lazy/try block — keep its shape) |
| `docs/pageindex.md` | MODIFY | Nine code-block imports at lines 29, 113, 166, 225, 258, 289, 341, 454, 509 + any prose references |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (target — what example / doc snippets should read)

```python
# Top-level public surface (after TASK-1328)
from parrot.knowledge.pageindex import (
    PageIndexLLMAdapter, PageIndexRetriever, PageIndexToolkit,
    build_page_index, md_to_tree, JSONTreeStore, NodeContentStore,
    HybridPageIndexSearch, TwoStepIngester, IngestedMarkdown,
)

# Module-level (used by some snippets in docs/pageindex.md)
from parrot.knowledge.pageindex.utils import get_page_tokens, add_node_text
from parrot.knowledge.pageindex.retriever import PageIndexRetriever
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
```

### Existing snippets to rewrite

```python
# examples/navigator_agent.py:21
from parrot.pageindex import PageIndexLLMAdapter

# examples/shoply/sample.py:36-37
from parrot.pageindex.retriever import PageIndexRetriever
from parrot.pageindex.llm_adapter import PageIndexLLMAdapter

# examples/graphindex/graphindex_corpus_agent.py:74
from parrot.pageindex import PageIndexLLMAdapter, PageIndexToolkit

# examples/pageindex/pageindex_compliance_agent.py:4  (docstring)
# :class:`parrot.pageindex.PageIndexToolkit` against a real PDF and a ...
# Line 46:
from parrot.pageindex import (
    ...
)

# examples/orchestrator/knowledge/ingest.py:49 (lazy/try block — keep its shape)
    from parrot.pageindex import PageIndexLLMAdapter, PageIndexToolkit
```

### docs/pageindex.md sites

```
docs/pageindex.md:29   from parrot.pageindex import (...)
docs/pageindex.md:113  from parrot.pageindex import PageIndexLLMAdapter
docs/pageindex.md:166  from parrot.pageindex import build_page_index, PageIndexLLMAdapter
docs/pageindex.md:225  from parrot.pageindex import md_to_tree, PageIndexLLMAdapter
docs/pageindex.md:258  from parrot.pageindex import PageIndexRetriever
docs/pageindex.md:289  from parrot.pageindex.utils import get_page_tokens
docs/pageindex.md:341  from parrot.pageindex import PageIndexLLMAdapter, PageIndexRetriever
docs/pageindex.md:454  from parrot.pageindex import (...)
docs/pageindex.md:509  from parrot.pageindex.utils import (...)
```
Each line should change `parrot.pageindex` → `parrot.knowledge.pageindex` while preserving the surrounding code-block structure.

### Does NOT Exist

- ~~A `parrot.pageindex` install entry point or CLI~~ — there is no console script tied to the old path; the docs do not advertise one.
- ~~An `examples/pageindex/` Python package import named `examples.pageindex`~~ — `examples/` is not a package; the directory name is cosmetic and is left as-is.
- ~~A separately built `site/pageindex.html` that must be hand-edited~~ — `site/` is generated by `mkdocs` from `docs/`; updating `docs/pageindex.md` is sufficient. If a CI publishes the site, that pipeline will re-render.

---

## Implementation Notes

### Procedure

```bash
# 1. Rewrite import paths in example scripts (5 files)
sed -i 's/from parrot\.pageindex/from parrot.knowledge.pageindex/g' \
  examples/navigator_agent.py \
  examples/shoply/sample.py \
  examples/graphindex/graphindex_corpus_agent.py \
  examples/pageindex/pageindex_compliance_agent.py \
  examples/orchestrator/knowledge/ingest.py

# 2. Also rewrite the docstring :class: reference in pageindex_compliance_agent.py
sed -i 's/parrot\.pageindex\.PageIndexToolkit/parrot.knowledge.pageindex.PageIndexToolkit/g' \
  examples/pageindex/pageindex_compliance_agent.py

# 3. Rewrite docs/pageindex.md (covers code blocks + any prose references)
sed -i 's/parrot\.pageindex/parrot.knowledge.pageindex/g' docs/pageindex.md

# 4. Verify
grep -rn 'parrot\.pageindex' examples/ docs/pageindex.md && echo "STALE REFS FOUND" \
  || echo "examples and docs clean"

# 5. Optional smoke: byte-compile example files to catch syntax errors introduced by sed
source .venv/bin/activate
python -m py_compile examples/navigator_agent.py examples/shoply/sample.py \
  examples/graphindex/graphindex_corpus_agent.py \
  examples/pageindex/pageindex_compliance_agent.py \
  examples/orchestrator/knowledge/ingest.py
```

### Key Constraints

- The `examples/orchestrator/knowledge/ingest.py:49` import lives inside a `try` block (likely a graceful-degradation pattern). Do not flatten the try — only the module path inside it changes.
- `docs/pageindex.md` may have inline backticks like `parrot.pageindex.foo` in prose. The sed above catches them too. Visually scan the diff afterwards to confirm nothing got broken (e.g. `parrot.pageindexing` would be wrongly rewritten — but no such word exists in the file; verify with `grep -n 'pageindexing' docs/pageindex.md` → expect zero hits).
- Do not edit any file in `site/` (mkdocs build output).
- Do not touch files in `sdd/proposals/`, `sdd/tasks/completed/`, or `sdd/tasks/archived/`.

### References in Codebase

- The new import paths resolve because TASK-1328 placed the package at `parrot.knowledge.pageindex` and re-exported the public surface from its `__init__.py`.
- `docs/pageindex.md` is the user-facing reference; mismatches here are the most visible regression to library consumers.

---

## Acceptance Criteria

- [ ] `grep -rn 'parrot\.pageindex' examples/` returns ZERO matches.
- [ ] `grep -n 'parrot\.pageindex' docs/pageindex.md` returns ZERO matches.
- [ ] `python -m py_compile examples/navigator_agent.py examples/shoply/sample.py examples/graphindex/graphindex_corpus_agent.py examples/pageindex/pageindex_compliance_agent.py examples/orchestrator/knowledge/ingest.py` succeeds.
- [ ] The `examples/pageindex_compliance_agent.py` module docstring (top of file) now reads `:class:`parrot.knowledge.pageindex.PageIndexToolkit`` (or equivalent verified by grep).
- [ ] `examples/pageindex/` directory still exists (directory NOT renamed; only file contents updated).
- [ ] All nine import code blocks in `docs/pageindex.md` use `parrot.knowledge.pageindex…` paths (visual diff inspection).

---

## Test Specification

No pytest tests. Verification is grep-based and byte-compile.

```bash
source .venv/bin/activate

# Expected: empty output
grep -rn 'parrot\.pageindex' examples/ docs/pageindex.md

# Expected: succeeds silently
python -m py_compile \
  examples/navigator_agent.py \
  examples/shoply/sample.py \
  examples/graphindex/graphindex_corpus_agent.py \
  examples/pageindex/pageindex_compliance_agent.py \
  examples/orchestrator/knowledge/ingest.py

# Expected: nine references using the new path
grep -c 'parrot\.knowledge\.pageindex' docs/pageindex.md
# Should be ≥ 9 (the rewritten code blocks); exact count may be higher if prose
# references existed.
```

---

### Completion Note

Completed by sdd-worker 2026-05-28.

Updated 4 example scripts (5 import statements) using `sed -i 's/from parrot.pageindex/from parrot.knowledge.pageindex/g'` plus a separate pass for the docstring `:class:` ref in `pageindex_compliance_agent.py`. Updated `docs/pageindex.md` (9 sites, all code blocks).

File `examples/graphindex/graphindex_corpus_agent.py` is NOT tracked by git (untracked in main repo) and therefore absent from the worktree — skipped. The spec listed it as a site to update but it has no git-tracked file.

`grep -rn 'parrot.pageindex' examples/ docs/pageindex.md` returns zero matches. `python -m py_compile` on 4 example files passed. `grep -c 'parrot.knowledge.pageindex' docs/pageindex.md` = 9.
