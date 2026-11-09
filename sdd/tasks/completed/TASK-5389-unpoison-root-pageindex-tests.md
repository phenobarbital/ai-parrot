# TASK-5389: Unpoison the four root pageindex test modules (plain imports)

**Feature**: FEAT-852 — Unpoison the root `tests/knowledge/pageindex` tree
**Spec**: `sdd/specs/pageindex-test-embedding-store-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:91822a3b8548`

---

## Context

The four test modules under the root `tests/knowledge/pageindex/` pre-register a
bare stub `parrot.knowledge.pageindex` in `sys.modules` (`__path__` set,
`__init__` never executed) and load submodules by file path through their own
`_load_module` helper. Under that stub the package's own relative imports
re-enter mid-execution:

`embedding_store.py:41` `from .hybrid_search import key_item_text` →
`pageindex/__init__.py:21` `from .toolkit import PageIndexToolkit` →
`toolkit.py:40` `from .embedding_store import NodeEmbeddingStore` **while
`embedding_store` is still executing** → `ImportError: cannot import name
'NodeEmbeddingStore'`. The half-built module stays in `sys.modules`, so every
later consumer sees `AttributeError: module '…embedding_store' has no attribute
'NodeEmbeddingStore'`.

Consequences on `dev`: 6 collection errors + 2 failed in the `test-core` CI job,
and all four files' coverage silently skipped on every run (including the
FEAT-844 guard restored by PR #2047).

**This is not a production circular import.** Verified on `0341c1be77`:
`python -c "import parrot.knowledge.pageindex.embedding_store as m; m.NodeEmbeddingStore"`
succeeds, with or without importing the package first. The stated reason for the
stub — "`aiohttp_cors` not installed in CI" — is stale: `aiohttp-cors>=0.8.1` is a
required core dependency (`packages/ai-parrot/pyproject.toml:149`) and CI runs
`uv sync --all-packages --extra scheduler`.

Local repro before the fix:
`pytest tests/knowledge/pageindex -q --continue-on-collection-errors` → `4 errors in 0.56s`.

---

## Scope

Replace the stub / path-loading preamble in all four modules with ordinary
absolute imports, and rewrite the module docstrings' now-false "Import note"
paragraphs. Remove every import that becomes unused as a result.

The module-scope names the test bodies use — `NodeEmbeddingStore`,
`HybridPageIndexSearch`, `FlatMatrixSearch`, `embedding_tree_walk`,
`PageIndexToolkit` — keep the **same names and the same module scope**, so **no
test body, fixture or assertion changes**.

**NOT in scope**:
- Any file under `packages/ai-parrot/src/parrot/knowledge/pageindex/`. The
  production import graph is correct and must not be touched (spec AC8).
- `tests/test_stub_isolation.py`, `tests/knowledge/pageindex/__init__.py` and the
  `ci.yml` comment — those are TASK-5390.
- `tests/knowledge/wiki/test_cli.py` and `test_cli_checkpoint.py`. They are
  *victims*; they are expected to go green with no edit. Do not modify them.
- Rewriting test bodies, renaming fixtures, adding new test cases.

---

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `tests/knowledge/pageindex/test_embedding_store.py` | MODIFY | replace lines 1–50 (docstring + `_load_embedding_store_module` + bindings) |
| `tests/knowledge/pageindex/test_dense_rrf_fusion.py` | MODIFY | replace lines 1–69 (docstring + `_WT`/`_load_module` + stub + bindings) |
| `tests/knowledge/pageindex/test_embedding_beam_walk.py` | MODIFY | replace lines 1–66 (same shape) |
| `tests/knowledge/pageindex/test_toolkit_embedding_wiring.py` | MODIFY | replace lines 1–65 (same shape) |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `0341c1be77` (2026-11-09). Re-verify before writing code.

### Verified Imports

```python
from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore   # verified: embedding_store.py:47
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch  # verified: hybrid_search.py:57
from parrot.knowledge.pageindex.vector_walk import FlatMatrixSearch         # verified: vector_walk.py:36
from parrot.knowledge.pageindex.vector_walk import embedding_tree_walk      # verified: vector_walk.py:81 (async def)
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit             # verified: toolkit.py:161
```

All five import together in one process on `0341c1be77`.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py
class NodeEmbeddingStore:            # line 47

# packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py
class HybridPageIndexSearch:         # line 57

# packages/ai-parrot/src/parrot/knowledge/pageindex/vector_walk.py
class FlatMatrixSearch:              # line 36
async def embedding_tree_walk(       # line 81

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):   # line 161
```

### Which preamble imports stay (verified by counting uses in each file's body)

| File | KEEP | DROP (unused after the rewrite) |
|---|---|---|
| `test_embedding_store.py` | `pytest`, `numpy as np`, `from pathlib import Path` | `importlib.util`, `sys`, `json` (`json.` has **0** uses — already dead) |
| `test_dense_rrf_fusion.py` | `asyncio`, `Callable`, `AsyncMock`, `MagicMock`, `numpy as np`, `pytest` | `importlib.util`, `sys`, `Path`, `patch` (0 uses in body) |
| `test_embedding_beam_walk.py` | `asyncio`, `numpy as np`, `pytest` | `importlib.util`, `sys`, `types`, `Path` |
| `test_toolkit_embedding_wiring.py` | `MagicMock`, `patch`, `pytest` | `importlib.util`, `sys`, `types`, `Path` |

`from __future__ import annotations` stays in the three files that have it
(`test_dense_rrf_fusion.py`, `test_embedding_beam_walk.py`,
`test_toolkit_embedding_wiring.py`); `test_embedding_store.py` has none — do not
add one.

### Does NOT Exist

- ~~`tests/knowledge/pageindex/conftest.py`~~ — does not exist. Do **not** create
  one; the fix needs no fixture plumbing.
- ~~`tests/knowledge/__init__.py`~~ — does not exist and must NOT be added.
- ~~`parrot.knowledge.pageindex.FlatMatrixSearch`~~ — `FlatMatrixSearch` is **not**
  re-exported from the package `__init__.py`. Import it from
  `parrot.knowledge.pageindex.vector_walk`.
- ~~`parrot.knowledge.pageindex.embedding_store.key_item_text`~~ — `key_item_text`
  lives in `hybrid_search.py:52`; `embedding_store` only imports it.
- ~~`import numpy as np` in `test_toolkit_embedding_wiring.py`'s preamble~~ — that
  file has no top-level numpy import today. Do not add one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "tests/knowledge/pageindex/test_embedding_store.py", "action": "MODIFY"},
    {"path": "tests/knowledge/pageindex/test_dense_rrf_fusion.py", "action": "MODIFY"},
    {"path": "tests/knowledge/pageindex/test_embedding_beam_walk.py", "action": "MODIFY"},
    {"path": "tests/knowledge/pageindex/test_toolkit_embedding_wiring.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py#NodeEmbeddingStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py#HybridPageIndexSearch",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/vector_walk.py#FlatMatrixSearch",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/vector_walk.py#embedding_tree_walk",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

Plain absolute imports at the top of the module, above all executable code —
exactly as every file in `packages/ai-parrot/tests/knowledge/pageindex/` already
does (e.g. `test_hybrid_search.py`). Because nothing executable precedes the
imports any more, **no `# noqa: E402` survives**.

### Key Constraints

- Delete, do not rewrite: there is no replacement loader. The whole
  `_WT` / `_load_module` / `_load_embedding_store_module` / `_pkg_stub` apparatus
  goes away.
- Keep the binding names at module scope. `NodeEmbeddingStore = _es_mod.NodeEmbeddingStore`
  becomes an import of the same name; the bodies below are untouched.
- Rewrite the docstrings' "Import note". Leaving the stale rationale in place is
  what invites the next engineer to restore the trick (spec R1).
- The existing section banner comments (`# ----- Fixtures -----`) below the
  preamble stay exactly where they are.

### References in Codebase

- `packages/ai-parrot/tests/knowledge/pageindex/test_hybrid_search.py` — a sibling
  suite that imports the same package normally and passes.
- `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py:21` — the
  `from .toolkit import PageIndexToolkit` line that closes the cycle under a stub.

---

## Implementation Blueprint

### Steps (in order)

1. Re-verify each anchor with `grep -c` (counts below) — because the spec's table
   was verified at spec time and these are line-range replacements, an anchor
   that moved means the range moved too. A count of `0` is drift: stop and report.
2. For each of the four files, replace the stated line range with the block given
   below, verbatim. Work top-down, one file at a time, and re-check the file's
   line numbers after each edit (editing file A does not move file B, but
   re-reading is cheap insurance).
3. Rewrite the "Import note" paragraph in each docstring as shown — because the
   old note asserts two things that are false (`aiohttp_cors` missing;
   `toolkit.py` not importing the package `__init__`), and a false comment is
   what caused this defect to be re-introduced once already.
4. Run `ruff check tests/knowledge/pageindex/` and remove any import the rewrite
   stranded — the KEEP/DROP table above is the expected answer, but ruff is the
   authority.
5. Run the four files' tests, then the pageindex+wiki combination in **both**
   directory orders (see Validation Commands) — because the two wiki failures are
   collection-order dependent (spec R2), one order alone does not prove the fix.

### `tests/knowledge/pageindex/test_embedding_store.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'def _load_embedding_store_module():' tests/knowledge/pageindex/test_embedding_store.py)
# REPLACE lines 1-50 — from the opening docstring through
#   `NodeEmbeddingStore = _es_mod.NodeEmbeddingStore`
#   (anchor verified: tests/knowledge/pageindex/test_embedding_store.py:25,
#    final preamble line verified at :50)
# with:
"""Unit tests for FEAT-237: NodeEmbeddingStore (TASK-1546).

Covers:
  - content_key determinism and sensitivity.
  - build_tree_matrix shape, caching, and batch-embedding only misses.
  - load_tree_matrix returns mmap'd matrix.
  - invalidate_tree removes per-tree matrix but preserves global tier.
  - LRU eviction (basic).

Imports ``parrot.knowledge.pageindex.embedding_store`` normally (FEAT-852).
It previously loaded the module by file path to "bypass ``aiohttp_cors``",
which has been a required core dependency all along; the bypass registered a
stub package whose missing ``__init__`` made the package's own relative imports
re-enter ``embedding_store`` mid-execution, leaving a half-built module in
``sys.modules``. See issue:91822a3b8548 and tests/test_stub_isolation.py.
"""
from pathlib import Path

import numpy as np
import pytest

from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore
```

**Why this shape**: `NodeEmbeddingStore` stays a module-scope name, so the
`store` fixture at `:56` and every assertion below it are unchanged. `Path` stays
because the `store(tmp_path: Path)` fixture annotates with it; `json` goes
because `json.` has zero uses in the file (verified) — it was already dead. The
docstring now records *why* the old trick was wrong, so it is not restored.

### `tests/knowledge/pageindex/test_dense_rrf_fusion.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '_es_mod = _load_module(' tests/knowledge/pageindex/test_dense_rrf_fusion.py)
# REPLACE lines 1-69 — from the opening docstring through
#   `from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch  # noqa: E402`
#   (anchor verified: tests/knowledge/pageindex/test_dense_rrf_fusion.py:51,
#    final preamble line verified at :69)
# with:
"""Unit tests for FEAT-237 TASK-1547: _vec_rank dense signal + RRF fusion.

Tests:
  - _vec_rank returns ranked node_id list by cosine similarity.
  - _vec_rank returns [] when embedding_store or embed_fn is None.
  - _rrf_fuse handles 2 and 3 input lists correctly.
  - mark_dirty triggers embedding matrix invalidation.
  - Lazy matrix rebuild on first _vec_rank call after invalidation.
  - search(use_vec=False) is byte-identical to baseline (AC1).
  - search(use_vec=True) produces fused BM25 + LLM + dense results.

Imports ``parrot.knowledge.pageindex`` normally (FEAT-852) — see
tests/knowledge/pageindex/test_embedding_store.py for why the previous
``sys.modules`` package stub was removed (issue:91822a3b8548).
"""
from __future__ import annotations

import asyncio
from typing import Callable
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch
```

**Why**: this file carried *both* halves of the defect — the path loader for
`embedding_store` and the `_pkg_stub` that let the subsequent
`from …hybrid_search import …` run against a package with no `__init__`. Both
go; `patch` is dropped because it has 0 uses in the body (verified), while
`AsyncMock`/`MagicMock`/`asyncio`/`Callable` are all still used.

### `tests/knowledge/pageindex/test_embedding_beam_walk.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '_vw_mod = _load_module(' tests/knowledge/pageindex/test_embedding_beam_walk.py)
# REPLACE lines 1-66 — from the opening docstring through
#   `embedding_tree_walk = _vw_mod.embedding_tree_walk`
#   (anchor verified: tests/knowledge/pageindex/test_embedding_beam_walk.py:61,
#    final preamble line verified at :66)
# with:
"""Unit tests for FEAT-237 TASK-1548: embedding beam walk (Phase B).

Tests:
  - FlatMatrixSearch returns results sorted by descending cosine score.
  - embedding_tree_walk returns candidate node_ids.
  - Beam walk respects max_depth.
  - Beam walk respects beam_width.
  - use_embedding_walk=False does not affect search output (flag-gating).

Imports ``parrot.knowledge.pageindex`` normally (FEAT-852) — see
tests/knowledge/pageindex/test_embedding_store.py for why the previous
``sys.modules`` package stub was removed (issue:91822a3b8548).
"""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore
from parrot.knowledge.pageindex.vector_walk import FlatMatrixSearch, embedding_tree_walk
```

**Why**: `FlatMatrixSearch` and `embedding_tree_walk` are both in `vector_walk`
and neither is re-exported from the package `__init__`, so the submodule import
is the correct one (contract). `_DIM = 16` at `:73` and everything below it stay
untouched.

### `tests/knowledge/pageindex/test_toolkit_embedding_wiring.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.pageindex.toolkit import PageIndexToolkit  # noqa: E402' tests/knowledge/pageindex/test_toolkit_embedding_wiring.py)
# REPLACE lines 1-65 — from the opening docstring through
#   `from parrot.knowledge.pageindex.toolkit import PageIndexToolkit  # noqa: E402`
#   (anchor verified: tests/knowledge/pageindex/test_toolkit_embedding_wiring.py:65)
# with:
"""Integration tests for FEAT-237 TASK-1549: NodeEmbeddingStore wiring in PageIndexToolkit.

Tests:
  - Without embedding params, no store is created (backward compat).
  - With use_vec_rank=True, embedding store is constructed.
  - _search_for passes embedding_store + flags to HybridPageIndexSearch.
  - Publishing a generation prunes stale per-generation embedding matrices.

Imports ``parrot.knowledge.pageindex`` normally (FEAT-852). The old note here
claimed ``toolkit.py`` does not import the package ``__init__``; in fact
``toolkit.py:40`` imports ``.embedding_store``, which is exactly the leg that
closed the cycle once a stub package suppressed ``__init__``
(issue:91822a3b8548).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
```

**Why**: this is the file whose stale comment was most actively misleading, and
the one whose lost collection hid the FEAT-844 guard
(`test_publish_prunes_stale_generation_matrices`). The
`patch("parrot.embeddings.registry.EmbeddingRegistry")` call sites at `:119`,
`:135`, `:149`, `:180` and `:231` keep working: they patch a *dotted string*
target resolved at call time, which the preamble never affected.

### FILL IN checklist

- [ ] `# FILL IN: per-file unused-import sweep — run `ruff check tests/knowledge/pageindex/` after the four edits and delete exactly what it reports; bounded by the KEEP/DROP table in the Codebase Contract and AC6. Do not delete an import ruff does not flag.`
- [ ] `# FILL IN: if any `grep -c` in Steps 1 returns a count other than 1, stop and report the drift in the Completion Note instead of guessing a new line range — bounded by the spec's §6 "a count of 0 means the anchor is gone" rule.`

---

## Acceptance Criteria

- [ ] AC1 — `pytest tests/knowledge/pageindex -q` reports **0 collection errors**
      and every test in the four modules passes.
- [ ] AC2 — `pytest tests/knowledge/pageindex tests/mcp -q --continue-on-collection-errors`
      reports 0 errors (the issue's second repro).
- [ ] AC3 — `pytest tests/knowledge/pageindex tests/knowledge/wiki -q` passes **and**
      `pytest tests/knowledge/wiki tests/knowledge/pageindex -q` passes, including
      `test_cli_checkpoint.py::TestCheckpointCallSites::test_ingest_checkpoints` and
      `::test_checkpoint_call_site_policy_end_to_end`.
- [ ] AC4 — `grep -rn 'ModuleType("parrot' tests/` returns nothing, and
      `grep -rn '_load_module\|_load_embedding_store_module' tests/knowledge/pageindex/`
      returns nothing.
- [ ] AC5 — `ruff check tests/knowledge/pageindex/` is clean, and no
      `# noqa: E402` remains in the four files.
- [ ] AC6 — `git diff --name-only` shows **only** the four test files; nothing
      under `packages/ai-parrot/src/` is modified (spec AC8).

---

## Validation Commands

- `pytest tests/knowledge/pageindex/test_embedding_store.py -q`
- `pytest tests/knowledge/pageindex/test_dense_rrf_fusion.py -q`
- `pytest tests/knowledge/pageindex/test_embedding_beam_walk.py -q`
- `pytest tests/knowledge/pageindex/test_toolkit_embedding_wiring.py -q`
- `pytest tests/knowledge/wiki/test_cli.py -q`
- `pytest tests/knowledge/wiki/test_cli_checkpoint.py -q`

> Run them from the worktree with an **absolute** `PYTHONPATH` pointing at the
> worktree's `packages/ai-parrot/src` — the shared venv is editable-installed
> against the main checkout, so a bare `pytest` imports the wrong tree.
> The order-sensitivity check in AC3 needs the two directories in one
> invocation; a per-file run cannot show it.

---

## Test Specification

No new test module. The four existing modules are the test: they must collect and
pass, where today they do not collect at all. The order-dependent pair in
`tests/knowledge/wiki/test_cli_checkpoint.py` is the regression signal:

```python
# tests/knowledge/wiki/test_cli_checkpoint.py  (unchanged — must pass)
class TestCheckpointCallSites:
    def test_ingest_checkpoints(self): ...                      # :51-56  imports tests.knowledge.wiki.test_cli
    def test_checkpoint_call_site_policy_end_to_end(self): ...   # :114-125 same
```

Both currently die with
`AttributeError: module 'tests.knowledge.wiki.test_cli' has no attribute '_FakeTriageAdapter'`
when the pageindex modules collect first, because `test_cli.py:39` imports
`parrot.knowledge.pageindex.toolkit` and that entry is poisoned.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-test-embedding-store-fixes --feature-id FEAT-852`)
2. **Read the spec** at `sdd/specs/pageindex-test-embedding-store-fixes.spec.md`
3. **Depends-on**: none — this is the first task.
4. **Verify the Codebase Contract** before writing code: re-run every `grep -c`
   in the blueprint and confirm the five Verified Imports resolve.
5. **Update status** in `sdd/tasks/index/pageindex-test-embedding-store-fixes.json`
   → `"in-progress"` (set `started_at`) and commit only that index file.
6. **Commit** only the four test files:
   `fix(pageindex-test-embedding-store-fixes): TASK-5389 — unpoison root pageindex tests`
7. **Close** with `parrot sdd task close TASK-5389 pageindex-test-embedding-store-fixes verified`.

---

## Completion Note

<!-- Filled in by the implementing agent. -->
