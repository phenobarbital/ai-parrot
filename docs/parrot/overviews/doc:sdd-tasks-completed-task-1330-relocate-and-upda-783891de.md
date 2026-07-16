---
type: Wiki Overview
title: 'TASK-1330: Relocate `tests/test_pageindex/` and update test references'
id: doc:sdd-tasks-completed-task-1330-relocate-and-update-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'After TASK-1328 moves the source package, the test suite at `packages/ai-parrot/tests/test_pageindex/`
  still references `parrot.pageindex` (65 string occurrences across imports and `monkeypatch.setattr`
  target strings). The tests also need to move to mirror the new source layout '
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.knowledge.pageindex
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.hybrid_search
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.ingest
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.llm_adapter
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.pdf_to_markdown
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.retriever
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.schemas
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.toolkit
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.tree_ops
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.utils
  rel: mentions
---

# TASK-1330: Relocate `tests/test_pageindex/` and update test references

**Feature**: FEAT-198 — move-pageindex-kb
**Spec**: `sdd/specs/move-pageindex-kb.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1328
**Assigned-to**: unassigned

---

## Context

After TASK-1328 moves the source package, the test suite at `packages/ai-parrot/tests/test_pageindex/` still references `parrot.pageindex` (65 string occurrences across imports and `monkeypatch.setattr` target strings). The tests also need to move to mirror the new source layout — `tests/knowledge/pageindex/` to match the existing `tests/knowledge/graphindex/` convention. Implements §3 Module 3 of the spec.

This task also fixes the three cross-subsystem references in `tests/knowledge/graphindex/test_loader_extractor.py` (lines 144, 164, 165) that test the graphindex loader's PageIndex integration.

---

## Scope

- `git mv` all files in `packages/ai-parrot/tests/test_pageindex/` to `packages/ai-parrot/tests/knowledge/pageindex/` (16 entries: `__init__.py`, 13 `test_*.py` files, `e2e_pdf_test.py`, and the `fixtures/` directory).
- Inside the moved test files, rewrite every `parrot.pageindex` occurrence to `parrot.knowledge.pageindex`. This includes:
  - `from parrot.pageindex…` imports (real Python imports)
  - `monkeypatch.setattr("parrot.pageindex.X.Y", …)` target strings
  - `patch("parrot.pageindex.X.Y", …)` target strings
  - Module docstrings that mention `parrot.pageindex.X`
  - `caplog.at_level(..., logger="parrot.pageindex")` in `test_toolkit.py:947`
- In `packages/ai-parrot/tests/knowledge/graphindex/test_loader_extractor.py`, rewrite the three `parrot.pageindex` references at lines 144, 164, 165 to `parrot.knowledge.pageindex`.
- Run the relocated test suite and confirm pass count matches the pre-move baseline (see Implementation Notes).
- Delete the empty `packages/ai-parrot/tests/test_pageindex/` directory (including any `__pycache__/`).

**NOT in scope**:
- Production-source importers → TASK-1329.
- Examples and docs → TASK-1331.
- Repo-wide verification grep / lint / cleanup → TASK-1332.
- Adding new tests, refactoring existing tests, changing assertions, or altering fixtures.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/pageindex/__init__.py` | CREATE (`git mv`) | Test package init |
| `packages/ai-parrot/tests/knowledge/pageindex/test_adapter.py` | CREATE (`git mv`) | Rewrites: `parrot.pageindex.llm_adapter` / `.schemas` (2 imports at lines 6–7) |
| `packages/ai-parrot/tests/knowledge/pageindex/test_content_store.py` | CREATE (`git mv`) | Docstring line 1 + `parrot.pageindex.content_store` import line 8 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_folder_import.py` | CREATE (`git mv`) | 4 sites (lines 9, 10, 53, 54) |
| `packages/ai-parrot/tests/knowledge/pageindex/test_hybrid_search.py` | CREATE (`git mv`) | Docstring + ~9 monkeypatch target strings; verify all `parrot.pageindex.*` patches and the `find_node_by_id` import at line 186 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_ingest.py` | CREATE (`git mv`) | Docstring + import at line 8 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_pdf_to_markdown.py` | CREATE (`git mv`) | Docstring + import at line 9 + monkeypatch target at line 57 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_retriever.py` | CREATE (`git mv`) | 2 imports at lines 8–9 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_schemas.py` | CREATE (`git mv`) | Import at line 7 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_store.py` | CREATE (`git mv`) | Docstring + import + patch target (3 sites: lines 1, 10, 57) |
| `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py` | CREATE (`git mv`) | ~30 `parrot.pageindex.X` target strings + `caplog.at_level(..., logger="parrot.pageindex")` at line 947 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_tree_ops.py` | CREATE (`git mv`) | Docstring + 2 imports (lines 6, 12) |
| `packages/ai-parrot/tests/knowledge/pageindex/test_utils.py` | CREATE (`git mv`) | Import at line 6 |
| `packages/ai-parrot/tests/knowledge/pageindex/e2e_pdf_test.py` | CREATE (`git mv`) | 3 imports at lines 25–27 |
| `packages/ai-parrot/tests/knowledge/pageindex/fixtures/` | CREATE (`git mv`) | Move directory verbatim — no content changes |
| `packages/ai-parrot/tests/knowledge/graphindex/test_loader_extractor.py` | MODIFY | Line 144: import; lines 164, 165: monkeypatch target strings |
| `packages/ai-parrot/tests/test_pageindex/` | DELETE | Old directory removed after move |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (post-rewrite — what tests should use)

```python
# Public package surface (resolvable after TASK-1328)
from parrot.knowledge.pageindex import (
    PageIndexToolkit, PageIndexRetriever, PageIndexLLMAdapter,
    build_page_index, md_to_tree, HybridPageIndexSearch,
    JSONTreeStore, NodeContentStore, TwoStepIngester, IngestedMarkdown,
    PageIndexNode, TreeSearchResult, TocItem,
)
# Module-level access
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter, extract_json
from parrot.knowledge.pageindex.schemas import TocDetectionResult, TreeSearchResult
from parrot.knowledge.pageindex.retriever import PageIndexRetriever
from parrot.knowledge.pageindex.store import JSONTreeStore
from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.ingest import IngestedMarkdown, TwoStepIngester
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.pageindex.tree_ops import (...)
from parrot.knowledge.pageindex.utils import (...)
from parrot.knowledge.pageindex.pdf_to_markdown import (...)
```

### Monkeypatch / patch target strings to rewrite

The 65 occurrences are not just imports — many are *string* targets to `monkeypatch.setattr` or `unittest.mock.patch`. They must be rewritten too because they resolve via string lookup at test time. Known pattern types:

```python
# Type A — count_tokens / utility patches
monkeypatch.setattr("parrot.pageindex.utils.count_tokens", _approx)
monkeypatch.setattr("parrot.pageindex.md_builder.count_tokens", _approx)

# Type B — function-level patches inside hybrid_search / toolkit
monkeypatch.setattr("parrot.pageindex.hybrid_search.PageIndexRetriever.search", fake_search)
monkeypatch.setattr("parrot.pageindex.toolkit.PageIndexRetriever.search", fake_search)
monkeypatch.setattr("parrot.pageindex.toolkit.build_page_index", _build)

# Type C — store / mock.patch
with patch("parrot.pageindex.store.os.replace", side_effect=boom):

# Type D — caplog logger filter
with caplog.at_level(logging.WARNING, logger="parrot.pageindex"):
```

Every one of these must become `parrot.knowledge.pageindex.*`. A global `sed -i 's/parrot\.pageindex/parrot.knowledge.pageindex/g'` over the moved directory is acceptable here **because** test files contain no `name = "pageindex"` toolkit-identity literals (those live only in `src/parrot/.../toolkit.py`, which was handled by TASK-1328).

### Cross-subsystem test (separate file)

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_loader_extractor.py
# Line 144:
from parrot.pageindex.toolkit import PageIndexToolkit
# Lines 164-165:
monkeypatch.setattr("parrot.pageindex.utils.count_tokens", _approx)
monkeypatch.setattr("parrot.pageindex.md_builder.count_tokens", _approx)
```
Rewrite to `parrot.knowledge.pageindex.*`.

### Does NOT Exist

- ~~`parrot.pageindex` (post-TASK-1328)~~ — the package is gone; any leftover string target fails silently with `AttributeError` at test time (mock raises). Catch them with the grep in TASK-1332.
- ~~A separate `tests/knowledge/pageindex/__init__.py` template~~ — reuse the existing `tests/test_pageindex/__init__.py` content verbatim via `git mv`.

---

## Implementation Notes

### Baseline first — capture pre-move pass count

Before starting, on the current code (after TASK-1328 / TASK-1329 land):
```bash
source .venv/bin/activate
# Use the OLD path one last time before this task moves the files.
pytest packages/ai-parrot/tests/test_pageindex -v --no-header 2>&1 | tee /tmp/pageindex-baseline.log | tail -20
```
Record the `N passed` / `M skipped` numbers. The relocated suite must match exactly after this task.

> Note: at this point the suite may already be broken because TASK-1328 renamed the logger and TASK-1329 rewrote external importers. If the baseline does not match, capture the actual numbers (passed/failed/skipped) as the new "intent baseline" and ensure the relocated suite matches that.

### Procedure

```bash
# 1. Create the destination and git-mv each file (preserves history per file)
mkdir -p packages/ai-parrot/tests/knowledge/pageindex
git mv packages/ai-parrot/tests/test_pageindex/__init__.py \
       packages/ai-parrot/tests/knowledge/pageindex/__init__.py
git mv packages/ai-parrot/tests/test_pageindex/e2e_pdf_test.py \
       packages/ai-parrot/tests/knowledge/pageindex/e2e_pdf_test.py
for f in test_adapter.py test_content_store.py test_folder_import.py \
         test_hybrid_search.py test_ingest.py test_pdf_to_markdown.py \
         test_retriever.py test_schemas.py test_store.py test_toolkit.py \
         test_tree_ops.py test_utils.py; do
  git mv "packages/ai-parrot/tests/test_pageindex/$f" \
         "packages/ai-parrot/tests/knowledge/pageindex/$f"
done
git mv packages/ai-parrot/tests/test_pageindex/fixtures \
       packages/ai-parrot/tests/knowledge/pageindex/fixtures

# 2. Rewrite all `parrot.pageindex` strings to `parrot.knowledge.pageindex`
#    in the moved directory. A targeted sed is safe here because no
#    user-facing "pageindex" literal lives in test files.
find packages/ai-parrot/tests/knowledge/pageindex -name "*.py" -type f \
  -exec sed -i 's/parrot\.pageindex/parrot.knowledge.pageindex/g' {} +

# 3. Patch the cross-subsystem test (3 sites)
sed -i 's/parrot\.pageindex/parrot.knowledge.pageindex/g' \
  packages/ai-parrot/tests/knowledge/graphindex/test_loader_extractor.py

# 4. Confirm old test dir is gone (after sed runs, no .pyc left behind)
rm -rf packages/ai-parrot/tests/test_pageindex/__pycache__ 2>/dev/null
rmdir packages/ai-parrot/tests/test_pageindex 2>/dev/null && echo "old test dir removed"

# 5. Run the relocated suite
pytest packages/ai-parrot/tests/knowledge/pageindex -v --no-header 2>&1 | tee /tmp/pageindex-post.log | tail -20

# 6. Run cross-subsystem test
pytest packages/ai-parrot/tests/knowledge/graphindex/test_loader_extractor.py -v
```

### Key Constraints

- Do NOT modify assertions, fixtures, or test logic. Only path strings change.
- The `caplog.at_level(..., logger="parrot.pageindex")` in `test_toolkit.py:947` must become `logger="parrot.knowledge.pageindex"`. The sed handles this — but **verify** by grep after.
- Skipped tests (e.g. those requiring optional pymupdf4llm) should remain skipped; pass count refers to non-skipped tests.
- Do not run the entire repo suite — that's TASK-1332.

### References in Codebase

- `packages/ai-parrot/tests/knowledge/graphindex/` — pattern for a knowledge-subsystem test layout (`__init__.py`, sibling `test_*.py` files, optional fixtures).
- `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py` (post TASK-1328) — confirms public symbols available.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/tests/test_pageindex/` does NOT exist (`test ! -d` returns true).
- [ ] `packages/ai-parrot/tests/test_pageindex` does NOT appear in `git ls-files`.
- [ ] `packages/ai-parrot/tests/knowledge/pageindex/` exists with all 14 test files + `__init__.py` + `fixtures/` directory.
- [ ] `git log --follow packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py` shows pre-move history (rename detected).
- [ ] `grep -rn 'parrot\.pageindex' packages/ai-parrot/tests/knowledge/` returns ZERO matches.
- [ ] `grep -rn 'parrot\.pageindex' packages/ai-parrot/tests/` returns ZERO matches.
- [ ] `pytest packages/ai-parrot/tests/knowledge/pageindex -v` passes with the baseline pass/skip counts captured before the move (no new failures, no new skips).
- [ ] `pytest packages/ai-parrot/tests/knowledge/graphindex/test_loader_extractor.py -v` passes.
- [ ] `ruff check packages/ai-parrot/tests/knowledge/pageindex` returns 0 issues.
- [ ] The `caplog.at_level(..., logger="parrot.knowledge.pageindex")` line in `test_toolkit.py` exists (verify: `grep -n 'logger=\"parrot.knowledge.pageindex\"' packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py` shows one match).

---

## Test Specification

```bash
source .venv/bin/activate

# Pre-move baseline (captured before this task runs):
# (recorded earlier, e.g. "98 passed, 4 skipped in 12.3s")

# Post-move suite — must match the baseline
pytest packages/ai-parrot/tests/knowledge/pageindex -v

# Cross-subsystem test — must still pass
pytest packages/ai-parrot/tests/knowledge/graphindex/test_loader_extractor.py -v

# Targeted: ensure logger-name rewrite landed
grep -n 'logger="parrot.knowledge.pageindex"' \
  packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py
# Expected: exactly one match (line ~947)

# Targeted: ensure no stale references remain
! grep -rn 'parrot\.pageindex' packages/ai-parrot/tests/ \
  && echo "all test references updated"
```

---

### Completion Note

Completed by sdd-worker 2026-05-28.

All 16 entries (14 test files + `__init__.py` + `fixtures/` directory) moved via `git mv`. sed replaced all 65 `parrot.pageindex` occurrences across moved test files including monkeypatch target strings and the `caplog.at_level(logger="parrot.pageindex")` at test_toolkit.py:947.

Cross-subsystem test `test_loader_extractor.py` updated (3 sites: line 144 import, lines 164-165 monkeypatch strings).

Pre-move baseline (from main repo): **2 failed, 167 passed** — same 2 pre-existing failures in `test_adapter.py::TestPageIndexLLMAdapter` (test_ask_structured_native, test_ask_structured_fallback_to_json). Post-move suite with PYTHONPATH override: **2 failed, 167 passed** — identical counts, confirming no new failures.

Cross-subsystem test `test_loader_extractor.py`: **22 passed**.

ruff check: 12 pre-existing errors (same 12 in original location, all F401 unused imports). Not fixed — out of scope.
