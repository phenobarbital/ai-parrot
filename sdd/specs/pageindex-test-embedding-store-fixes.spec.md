---
type: feature
base_branch: dev
projects: [knowledge, testing]
tags: [pageindex, tests, collection, ci, import-hygiene]
---

# Feature Specification: Unpoison the root `tests/knowledge/pageindex` tree

**Feature ID**: FEAT-852
**Date**: 2026-11-09
**Author**: Jesus (via /sdd-fix issue:91822a3b8548)
**Status**: approved
**Target version**: 2.1.2

---

## 1. Motivation & Business Requirements

### Problem Statement

`dev`'s `test-core` job (`.github/workflows/ci.yml:312`,
`pytest tests/ -q --tb=short --ignore=tests/tools --continue-on-collection-errors`)
carries a standing **6 collection ERRORs + 2 FAILED** from a single cause.
Post-merge run 42616889870 (`9283fbdec7`) reported `2 failed, 6752 passed, 6 errors`;
run 42612925576 (`49a4d9198e`) was identical, so the breakage is standing, not new.

**Mechanism (verified, not inferred).** Four test modules under the root
`tests/knowledge/pageindex/` bypass the real package `__init__` by
pre-registering a bare stub `parrot.knowledge.pageindex` in `sys.modules`
(`__path__` set, `__init__` never executed) and then loading submodules by file
path through their own `_load_module` helper:

| File | Stub | `_load_module` |
|---|---|---|
| `tests/knowledge/pageindex/test_dense_rrf_fusion.py` | yes (`:60-67`) | yes (`:38`) |
| `tests/knowledge/pageindex/test_embedding_beam_walk.py` | yes (`:46-52`) | yes (`:33`) |
| `tests/knowledge/pageindex/test_embedding_store.py` | no | yes (`_load_embedding_store_module`, `:26`) |
| `tests/knowledge/pageindex/test_toolkit_embedding_wiring.py` | yes (`:46-52`) | yes (`:33`) |

Under that stub the otherwise benign cycle re-enters:
`embedding_store.py:41` `from .hybrid_search import key_item_text` →
`pageindex/__init__.py:21` `from .toolkit import PageIndexToolkit` →
`toolkit.py:40` `from .embedding_store import NodeEmbeddingStore` **while
`embedding_store` is still mid-execution** → `ImportError: cannot import name
'NodeEmbeddingStore'`. The half-built module stays in `sys.modules`, so every
later consumer gets `AttributeError: module '…embedding_store' has no attribute
'NodeEmbeddingStore'`.

**This is not a production circular import.** Verified on `dc146e7d26`:

```
python -c "import parrot.knowledge.pageindex.embedding_store as m; m.NodeEmbeddingStore"  # OK
python -c "import parrot.knowledge.pageindex as p; p.__file__"                            # OK
```

Only the stub shortcut breaks it, so the fix belongs in the tests — **not** in
`toolkit.py` or `embedding_store.py`.

**The stated rationale for the stub is stale.** All four docstrings claim the
package `__init__` "triggers `aiohttp_cors` (not installed in CI)".
`aiohttp-cors>=0.8.1` is a *required* dependency of core ai-parrot
(`packages/ai-parrot/pyproject.toml:149`) and CI runs
`uv sync --all-packages --extra scheduler`, so it is always installed.
`test_toolkit_embedding_wiring.py`'s claim that "toolkit.py does not import from
`parrot.knowledge.pageindex` package `__init__`" is also stale — `toolkit.py:40`
is exactly the relative import that closes the cycle.

**Knock-on (the 2 FAILED).** `tests/knowledge/wiki/test_cli.py:39` imports
`parrot.knowledge.pageindex.toolkit` at module level, so the poisoned entry makes
it fail to *collect*; `tests/knowledge/wiki/test_cli_checkpoint.py:53,114` then
dies with `AttributeError: module 'tests.knowledge.wiki.test_cli' has no attribute
'_FakeTriageAdapter'` in `TestCheckpointCallSites::test_ingest_checkpoints` and
`::test_checkpoint_call_site_policy_end_to_end`. Collection order picks the loser:
on 42616889870 the 3.11 job passed and only 3.12 failed; on 42612925576 it was
3.11. That intermittency is why the breakage reads as noise.

**Collateral.** Because these four files never collect on CI, **all of their
coverage is silently skipped on every run** — including the FEAT-844 guard
restored in PR #2047 (`test_publish_prunes_stale_generation_matrices`). The root
`tests/knowledge/pageindex/` tree contains *only* these four files and they have
no twin in `packages/ai-parrot/tests/knowledge/pageindex/` (that tree's
`test_embedding_store.py` is a different, smaller module), so this is ~4 files of
unique FEAT-237 embedding coverage lost, hidden behind "6 errors".

**Local repro** (unmodified `dc146e7d26`, no cross-test interference):

```
pytest tests/knowledge/pageindex -q --continue-on-collection-errors   # 4 errors in 0.56s
pytest tests/knowledge/pageindex/test_dense_rrf_fusion.py -q          # 1 collection error
```

### Goals

- G1 — The four root pageindex test modules collect and pass with **ordinary
  imports**: no `sys.modules` stub, no path-based module loading.
- G2 — `tests/knowledge/wiki/test_cli.py` collects and
  `tests/knowledge/wiki/test_cli_checkpoint.py`'s two `TestCheckpointCallSites`
  tests pass in a full-tree run, in any collection order.
- G3 — The class of defect cannot come back silently: a regression guard in the
  root `tests/` tree fails loudly if any root test module leaves a real
  `parrot.*` module replaced by a stand-in.
- G4 — Resolve the open question about `--continue-on-collection-errors` with a
  recorded decision, so a future reader knows why the flag is (or is not) there.

### Non-Goals (explicitly out of scope)

- Changing `embedding_store.py`, `toolkit.py`, `hybrid_search.py`,
  `vector_walk.py` or `pageindex/__init__.py` — production imports are correct
  and verified. Breaking the `__init__` → `toolkit` → `embedding_store` cycle is
  **not** this feature's job.
- Rewriting the test *bodies*, fixtures or assertions of the four modules. Only
  their import preamble and the now-stale docstring notes change.
- Moving the four files into `packages/ai-parrot/tests/` or deduplicating them
  against that tree.
- Fixing `test_cli_checkpoint.py`'s `import tests.knowledge.wiki.test_cli`
  cross-module coupling. It is fragile, but it is not the cause, and with the
  poisoning gone those two tests pass. Recorded in §8 as a follow-up.
- Auditing the other `sys.modules`-shadowing modules in
  `packages/ai-parrot/tests/` — FEAT-617 already covered that tree.

---

## 2. Architectural Design

### Overview

Delete the scaffolding, keep the tests. Each of the four modules loses its
`_WT` / `_load_module` / `_pkg_stub` preamble and gains plain
`from parrot.knowledge.pageindex.<submodule> import <Name>` statements. Nothing
else in the files moves.

Two safeguards are added so the mode of failure cannot reappear unnoticed:

1. `tests/knowledge/pageindex/__init__.py` — gives the four modules a
   package-qualified identity (`tests.knowledge.pageindex.*`), matching
   `tests/knowledge/wiki/` and the `packages/ai-parrot/tests/knowledge/pageindex/`
   twin, so the same-named `test_embedding_store.py` in the two trees can never
   collide on module identity (FEAT-720).
2. `tests/test_stub_isolation.py` — the root-tree counterpart of
   `packages/ai-parrot/tests/test_conftest_stub_isolation.py` (FEAT-617): a live
   check that named `parrot.*` modules still resolve to a real file, plus a
   static scan that no file under root `tests/` installs a `types.ModuleType`
   stand-in for an importable `parrot.*` name.

### Component Diagram

```
tests/knowledge/pageindex/*.py ──(plain import)──→ parrot.knowledge.pageindex.*
         │                                                   ▲
         │  no stub, no _load_module                         │ real __init__ runs
         ▼                                                   │
tests/test_stub_isolation.py ──(asserts __file__ is real)────┘
         │
         └──(static scan of tests/**.py)──→ no ModuleType stand-in for parrot.*
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.knowledge.pageindex.embedding_store` | imports | plain import replaces the path load |
| `parrot.knowledge.pageindex.hybrid_search` | imports | plain import replaces the stub shortcut |
| `parrot.knowledge.pageindex.vector_walk` | imports | plain import replaces the path load |
| `parrot.knowledge.pageindex.toolkit` | imports | plain import replaces the stub shortcut |
| `packages/ai-parrot/tests/test_conftest_stub_isolation.py` | pattern source | the root guard is modelled on it; the packages guard is NOT edited |
| `.github/workflows/ci.yml` `test-core` | comment only | records the `--continue-on-collection-errors` decision |

### Data Models

None — this feature adds no models.

### New Public Interfaces

None.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: unpoison the four test modules | yes | exact import lines fixed in §6; delete-only elsewhere | — |
| M2: root-tree stub-isolation guard | yes | modelled verbatim on the FEAT-617 guard; names fixed in §6 | — |

### Module 1: Unpoison the four root pageindex test modules
- **Path**: `tests/knowledge/pageindex/test_dense_rrf_fusion.py`,
  `tests/knowledge/pageindex/test_embedding_beam_walk.py`,
  `tests/knowledge/pageindex/test_embedding_store.py`,
  `tests/knowledge/pageindex/test_toolkit_embedding_wiring.py`
- **Responsibility**: Replace the stub/path-loading preamble with ordinary
  imports and correct the stale "Import note" docstrings.
- **Depends on**: nothing (first task).
- **Interface Skeleton** — the exact preamble each file ends with:

  ```python
  # tests/knowledge/pageindex/test_embedding_store.py
  from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore

  # tests/knowledge/pageindex/test_dense_rrf_fusion.py
  from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore
  from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch

  # tests/knowledge/pageindex/test_embedding_beam_walk.py
  from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore
  from parrot.knowledge.pageindex.vector_walk import FlatMatrixSearch, embedding_tree_walk

  # tests/knowledge/pageindex/test_toolkit_embedding_wiring.py
  from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore
  from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch
  from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
  ```

  Removed from every file it appears in: `_WT`, `_load_module`,
  `_load_embedding_store_module`, the `_pkg_stub` block, the `_es_mod` / `_vw_mod`
  bindings, the `# noqa: E402` markers that only existed because imports sat below
  executable code, and any `import importlib.util` / `import types` / `import sys`
  / `from pathlib import Path` left unused afterwards. Module-scope names that the
  test bodies use (`NodeEmbeddingStore`, `HybridPageIndexSearch`,
  `FlatMatrixSearch`, `embedding_tree_walk`, `PageIndexToolkit`) keep the **same
  names**, so no test body changes.

### Module 2: Root-tree stub-isolation guard
- **Path**: `tests/test_stub_isolation.py` (new),
  `tests/knowledge/pageindex/__init__.py` (new, empty),
  `.github/workflows/ci.yml` (comment only)
- **Responsibility**: Make the next occurrence of this defect fail loudly rather
  than hide as a collection error, and record the CI-flag decision.
- **Depends on**: Module 1.
- **Interface Skeleton**:

  ```python
  # tests/test_stub_isolation.py  (new)
  """Regression guard: a root test module may not leave a real parrot.* module stubbed.

  FEAT-852 / issue:91822a3b8548 — the root counterpart of
  packages/ai-parrot/tests/test_conftest_stub_isolation.py (FEAT-617).
  Do not delete this module.
  """

  MUST_NOT_BE_SHADOWED: tuple[str, ...] = (
      "parrot.knowledge.pageindex",
      "parrot.knowledge.pageindex.embedding_store",
      "parrot.knowledge.pageindex.hybrid_search",
      "parrot.knowledge.pageindex.toolkit",
      "parrot.knowledge.pageindex.vector_walk",
  )

  @pytest.mark.parametrize("name", MUST_NOT_BE_SHADOWED)
  def test_real_modules_are_not_shadowed(name: str) -> None:
      """A genuinely importable parrot module must resolve to a real file on disk."""

  def test_no_test_module_registers_a_parrot_stub() -> None:
      """No file under tests/ may assign a ModuleType stand-in into sys.modules for a parrot.* name."""
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_real_modules_are_not_shadowed[parrot.knowledge.pageindex.embedding_store]` | M2 | The live `sys.modules` entry has a real `__file__` that exists |
| `test_real_modules_are_not_shadowed[parrot.knowledge.pageindex.toolkit]` | M2 | Same, for the module whose import closes the cycle |
| `test_no_test_module_registers_a_parrot_stub` | M2 | Static scan of `tests/**/*.py` finds no `ModuleType("parrot…")` → `sys.modules[…]` assignment |

### Integration Tests

| Test | Description |
|---|---|
| The four `tests/knowledge/pageindex/` modules | Collect and pass unchanged after the import rewrite |
| `tests/knowledge/wiki/test_cli.py` | Collects (no poisoned `parrot.knowledge.pageindex.toolkit`) |
| `tests/knowledge/wiki/test_cli_checkpoint.py::TestCheckpointCallSites` | Both call-site tests pass, in either collection order |

### Validation Contract

tests:
- tests/knowledge/pageindex/test_dense_rrf_fusion.py
- tests/knowledge/pageindex/test_embedding_beam_walk.py
- tests/knowledge/pageindex/test_embedding_store.py
- tests/knowledge/pageindex/test_toolkit_embedding_wiring.py
- tests/knowledge/wiki/test_cli.py
- tests/knowledge/wiki/test_cli_checkpoint.py
- tests/test_stub_isolation.py
markers: none

### Test Data / Fixtures

No new fixtures. The existing `small_tree` / `deep_tree` / `mock_embed_fn` /
`mock_adapter` / `mock_store` fixtures in the four modules are untouched.

---

## 5. Acceptance Criteria

- [ ] AC1 — `pytest tests/knowledge/pageindex -q` reports **0 collection errors**
      and all tests in the four modules pass.
- [ ] AC2 — `pytest tests/knowledge/pageindex tests/mcp -q --continue-on-collection-errors`
      reports 0 errors (the issue's second repro).
- [ ] AC3 — `pytest tests/knowledge/pageindex tests/knowledge/wiki -q` passes,
      including `test_cli_checkpoint.py::TestCheckpointCallSites::test_ingest_checkpoints`
      and `::test_checkpoint_call_site_policy_end_to_end`, **and** passes with the
      directories given in the reverse order.
- [ ] AC4 — `grep -rn 'ModuleType("parrot' tests/` returns nothing, and no file
      under `tests/knowledge/pageindex/` defines `_load_module` or
      `_load_embedding_store_module`.
- [ ] AC5 — `pytest tests/test_stub_isolation.py -q` passes, and
      `test_no_test_module_registers_a_parrot_stub` is demonstrated to fail when a
      stub is reintroduced (checked once by hand, then reverted).
- [ ] AC6 — `ruff check` is clean on every changed file (no leftover unused
      `importlib`/`types`/`sys`/`Path` import, no stranded `# noqa: E402`).
- [ ] AC7 — The `--continue-on-collection-errors` decision from §8/Decisions is
      recorded as a comment beside the flag in `.github/workflows/ci.yml`.
- [ ] AC8 — No file under `packages/ai-parrot/src/parrot/knowledge/pageindex/` is
      modified by this feature.

---

## 6. Codebase Contract

> Verified against `dc146e7d26` (2026-11-09).

### Verified Imports

```python
from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore          # verified: embedding_store.py:47
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch         # verified: hybrid_search.py:57
from parrot.knowledge.pageindex.vector_walk import FlatMatrixSearch                # verified: vector_walk.py:36
from parrot.knowledge.pageindex.vector_walk import embedding_tree_walk             # verified: vector_walk.py:81 (async def)
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit                    # verified: toolkit.py:161
```

All five verified importable in one process on `dc146e7d26`:
`python -c "import parrot.knowledge.pageindex as p; from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore"` → OK.

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py
from .hybrid_search import key_item_text        # line 41  — the cycle's first leg
class NodeEmbeddingStore:                       # line 47

# packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py
from .toolkit import PageIndexToolkit           # line 21  — the cycle's second leg

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
from .embedding_store import NodeEmbeddingStore # line 40  — the cycle's third leg
class PageIndexToolkit(AbstractToolkit):        # line 161

# packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py
def key_item_text(node: dict) -> str:           # line 52
class HybridPageIndexSearch:                    # line 57

# packages/ai-parrot/src/parrot/knowledge/pageindex/vector_walk.py
class FlatMatrixSearch:                         # line 36
async def embedding_tree_walk(                  # line 81
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `tests/test_stub_isolation.py` | `importlib.import_module` + `sys.modules` | live check | pattern: `packages/ai-parrot/tests/test_conftest_stub_isolation.py:57-71` |
| `tests/knowledge/pageindex/__init__.py` | pytest module identity | package marker | sibling precedent: `tests/knowledge/wiki/__init__.py` exists |
| ci.yml comment | `test-core` run step | comment beside the flag | `.github/workflows/ci.yml:312` |

### Does NOT Exist (Anti-Hallucination)

- ~~`tests/knowledge/pageindex/conftest.py`~~ — does not exist; do not create one.
- ~~`tests/knowledge/conftest.py`~~ — does not exist.
- ~~`tests/knowledge/__init__.py`~~ — does **not** exist and must NOT be added:
  `tests/knowledge` resolves as a namespace package today and
  `tests/knowledge/wiki/__init__.py` already works through it. Adding it is out
  of scope and risks changing identity for the whole `tests/knowledge` subtree.
- ~~`tests/test_stub_isolation.py`~~ — does not exist yet; M2 creates it.
- ~~`tests/knowledge/pageindex/__init__.py`~~ — does not exist yet; M2 creates it.
- ~~`parrot.knowledge.pageindex.vector_walk.FlatMatrixSearch` exported from the
  package `__init__`~~ — it is not in `__init__.py`; import from the submodule.
- ~~a root `tests/conftest.py` stub helper such as `_stub_if_absent`~~ — the root
  `tests/conftest.py` performs **no** `sys.modules` manipulation at all
  (`grep -n "sys.modules" tests/conftest.py` → empty), so the root guard must not
  try to load it the way the FEAT-617 guard loads the packages conftest.

### Edit Sites (Blueprint Anchors)

> Verified against `dc146e7d26`. `/sdd-task` MUST re-run each `grep -c` before use.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `tests/knowledge/pageindex/test_embedding_store.py` | MODIFY | `def _load_embedding_store_module():` | `test_embedding_store.py:26` | 1 |
| `tests/knowledge/pageindex/test_dense_rrf_fusion.py` | MODIFY | `_es_mod = _load_module(` | `test_dense_rrf_fusion.py:51` | 1 |
| `tests/knowledge/pageindex/test_embedding_beam_walk.py` | MODIFY | `_vw_mod = _load_module(` | `test_embedding_beam_walk.py:61` | 1 |
| `tests/knowledge/pageindex/test_toolkit_embedding_wiring.py` | MODIFY | `from parrot.knowledge.pageindex.toolkit import PageIndexToolkit  # noqa: E402` | `test_toolkit_embedding_wiring.py:65` | 1 |
| `tests/test_stub_isolation.py` | CREATE | — | — | — |
| `tests/knowledge/pageindex/__init__.py` | CREATE | — | — | — |
| `.github/workflows/ci.yml` | MODIFY | `run: uv run pytest tests/ -q --tb=short --ignore=tests/tools --continue-on-collection-errors` | `ci.yml:312` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Ordinary absolute imports at module top, above all executable code — no
  `# noqa: E402`, because there is nothing left for the imports to sit below.
- The root guard mirrors `packages/ai-parrot/tests/test_conftest_stub_isolation.py`
  in shape (a parametrized live check + a static source scan) but **not** in
  content: the root `tests/conftest.py` installs no stubs, so there is no
  `_stub_if_absent` to exercise and no conftest to load by path.
- Google-style docstrings, type hints, 120-column lines (repo conventions).

### Known Risks / Gotchas

- **R1 — the docstrings lie, not just the code.** Every one of the four files
  explains the trick in its module docstring. Deleting the code and leaving the
  "Import note" invites the next reader to restore it. The notes must be rewritten
  (or dropped) in the same task.
- **R2 — order-dependent green.** The two wiki failures appear only when the
  pageindex modules collect *before* `tests/knowledge/wiki/test_cli.py`. AC3
  therefore requires running both directory orders, not one.
- **R3 — unused imports after the delete.** `importlib.util`, `types`, `sys`,
  `Path` and `numpy`-adjacent helpers may become unused in some files and stay
  used in others (`sys`/`Path` are still used by some test bodies). Decide per
  file from `ruff check`, never by blanket deletion.
- **R4 — root-tree test identity.** Adding `tests/knowledge/pageindex/__init__.py`
  changes those modules' import names to `tests.knowledge.pageindex.*`. Nothing
  imports them by name today
  (`grep -rn "tests.knowledge.pageindex" tests/ packages/` → only the files
  themselves), so this is safe; re-check before committing.
- **R5 — the shared venv is installed against the main checkout.** Inside the
  worktree, run pytest with an absolute
  `PYTHONPATH=<wt>/packages/ai-parrot/src` or the run silently imports the main
  checkout's `parrot` (see the worktree-validation memo). For this feature the
  *tests* are what changed, not `parrot`, so a stale `parrot` import would still
  give a correct verdict — but set it anyway.
- **R6 — `--continue-on-collection-errors` does not hide a red job.** The job
  already fails on these errors; the flag only hides *which* files were skipped.
  Removing it would make the job abort at the first collection error and report
  less, not more.

### External Dependencies

None added. `aiohttp-cors>=0.8.1` is already a required core dependency
(`packages/ai-parrot/pyproject.toml:149`).

---

## Decisions

```yaml
schema_version: 1
document_id: pageindex-test-embedding-store-fixes
entries:
  - id: no-sys-modules-stub-for-real-packages
    statement: A test module must never pre-register a stand-in in sys.modules for a parrot package that is genuinely importable.
    relation: forbids
    about: [testing]
    targets:
      - dir:tests/knowledge/pageindex
      - file:tests/test_stub_isolation.py
    contradicts: []
    supersedes: []
    rationale: >
      A bare package stub skips __init__ and re-enters the package's own relative
      imports mid-execution, leaving a half-built module in sys.modules that
      poisons every later consumer. The production import graph is correct; the
      shortcut is what breaks.
    rejected_alternatives:
      - Break the __init__ -> toolkit -> embedding_store cycle in production code (the cycle is benign under normal import).
      - Move key_item_text out of hybrid_search to shorten the cycle (churn in production code for a test-only defect).
  - id: keep-continue-on-collection-errors
    statement: The test-core job keeps --continue-on-collection-errors, and the guard test is what makes a silent skip fail loudly.
    relation: constrains
    about: [testing]
    targets: [file:.github/workflows/ci.yml]
    contradicts: []
    supersedes: []
    rationale: >
      The flag does not mask a red job — collection errors already fail it. It only
      lets one run report every failure instead of aborting at the first. The real
      gap was that a never-collected file looked routine; tests/test_stub_isolation.py
      closes that gap directly.
    rejected_alternatives:
      - Drop the flag so collection errors abort the run (loses the rest of the signal and still would not name the cause).
```

---

## 8. Open Questions

- [x] Does the job keep `--continue-on-collection-errors`? — **Resolved**: yes,
      with the rationale recorded in Decisions and as a ci.yml comment. *Owner: Jesus*
- [ ] Should `tests/knowledge/wiki/test_cli_checkpoint.py` stop importing
      `tests.knowledge.wiki.test_cli` for `_FakeTriageAdapter` (move the fake into a
      shared fixture module)? Out of scope here; file as a ledger item after merge.
      *Owner: Jesus*
- [ ] Should the four root files move under
      `packages/ai-parrot/tests/knowledge/pageindex/`, where the rest of the
      pageindex suite lives and where the packages-tree guard already applies?
      Out of scope here. *Owner: Jesus*

---

## 9. Design Research Cross-Check

> Status: skipped — the mechanism is verified by direct repro and the fix is a
> delete-only import rewrite with no design surface. The adversarial pass happens
> at code-review time over the diff instead.

---

## 10. Documentation

> **Policy**: none. No wiki page: this is test-tree import hygiene, already
> described by the module docstrings, the guard test's own docstring and the
> Decisions block above.

---

## Resolves

- `issue:91822a3b8548` — Root pageindex tests' `sys.modules` stub poisons
  `embedding_store`: 6 collection errors, 2 red wiki tests, 4 files silently
  skipped on CI.
