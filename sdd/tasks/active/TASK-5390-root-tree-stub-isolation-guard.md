# TASK-5390: Root-tree stub-isolation guard + pageindex package marker + CI decision comment

**Feature**: FEAT-852 — Unpoison the root `tests/knowledge/pageindex` tree
**Spec**: `sdd/specs/pageindex-test-embedding-store-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5389
**Assigned-to**: unassigned
**Discovered-from**: `issue:91822a3b8548`

---

## Context

TASK-5389 removes the `sys.modules` package stub that poisoned
`parrot.knowledge.pageindex.embedding_store`. Nothing stops it coming back: the
root `tests/` tree has **no** equivalent of
`packages/ai-parrot/tests/test_conftest_stub_isolation.py`, the guard FEAT-617
added to the packages tree after this same class of bug was fixed there twice
(FEAT-268, then both halves of FEAT-617).

Worse, the failure mode is *quiet*: a stubbed package surfaces as a **collection
error**, and the `test-core` job runs with `--continue-on-collection-errors`
(`.github/workflows/ci.yml:312`), so four never-collected files read as routine
noise rather than four files of lost coverage.

This task closes both gaps: a loud guard, and a recorded decision about the CI
flag so the next reader knows it was considered, not overlooked.

---

## Scope

1. Create `tests/test_stub_isolation.py` — the root-tree counterpart of the
   FEAT-617 guard: a parametrized live check that the pageindex modules resolve
   to real files, plus a static scan asserting no file under `tests/` installs a
   `ModuleType` stand-in for a `parrot.*` name.
2. Create `tests/knowledge/pageindex/__init__.py` (empty) so those four modules
   get a package-qualified identity (`tests.knowledge.pageindex.*`), matching
   `tests/knowledge/wiki/` and the `packages/ai-parrot/tests/knowledge/pageindex/`
   twin — which contains a same-named `test_embedding_store.py` (FEAT-720).
3. Add a comment above the `test-core` run step in `.github/workflows/ci.yml`
   recording why `--continue-on-collection-errors` stays.

**NOT in scope**:
- Editing `packages/ai-parrot/tests/test_conftest_stub_isolation.py`. The root
  guard is modelled on it; the packages guard is not touched.
- Adding `tests/knowledge/__init__.py` — see "Does NOT Exist".
- Adding a root `tests/conftest.py` stub helper. The root conftest performs no
  `sys.modules` manipulation at all and must keep performing none.
- Changing the pytest invocation, flags or job matrix in `ci.yml` (comment only).
- Any `parrot` source file.

---

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `tests/test_stub_isolation.py` | CREATE | the guard, full content in the blueprint |
| `tests/knowledge/pageindex/__init__.py` | CREATE | empty file (0 bytes) |
| `.github/workflows/ci.yml` | MODIFY | comment above `- name: Run core tests` (`:311`) |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `0341c1be77` (2026-11-09). Re-verify before writing code.

### Verified Imports

```python
# stdlib only — the guard adds no parrot import at module scope on purpose,
# so the guard itself can never be the thing that poisons a module.
import importlib
import re
import sys
from pathlib import Path

import pytest
```

The names the guard asserts about (resolved dynamically via
`importlib.import_module`, never imported at module scope):

```python
"parrot.knowledge.pageindex"                   # verified: __init__.py:1
"parrot.knowledge.pageindex.embedding_store"   # verified: embedding_store.py:47  (NodeEmbeddingStore)
"parrot.knowledge.pageindex.hybrid_search"     # verified: hybrid_search.py:57    (HybridPageIndexSearch)
"parrot.knowledge.pageindex.toolkit"           # verified: toolkit.py:161         (PageIndexToolkit)
"parrot.knowledge.pageindex.vector_walk"       # verified: vector_walk.py:36      (FlatMatrixSearch)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/tests/test_conftest_stub_isolation.py  — the pattern source (DO NOT EDIT)
MUST_NOT_BE_SHADOWED = (...)                                      # line 41
@pytest.mark.parametrize("name", MUST_NOT_BE_SHADOWED)            # line 58
def test_real_modules_are_not_shadowed(name: str) -> None:        # line 59
    module = importlib.import_module(name)                        # line 65
    assert getattr(module, "__file__", None) is not None          # line 66
```

### Facts the guard depends on (verified)

- `grep -n "sys.modules" tests/conftest.py` → **empty**. The root conftest
  installs no stubs, so the root guard has **no** `_stub_if_absent` to exercise
  and no conftest to load by path. It must not try.
- `tests/__init__.py` **exists**; `tests/knowledge/__init__.py` does **not**;
  `tests/knowledge/wiki/__init__.py` **exists** — so `tests.knowledge` already
  resolves as a namespace package and `import tests.knowledge.wiki.test_cli`
  works today (`test_cli_checkpoint.py:53`).
- Nothing imports `tests.knowledge.pageindex.*` by name
  (`grep -rn "tests\.knowledge\.pageindex" tests/ packages/*/tests/` → no hits),
  so adding the package marker breaks no importer.
- `grep -c 'run: uv run pytest tests/ -q --tb=short --ignore=tests/tools --continue-on-collection-errors' .github/workflows/ci.yml` → **1**.

### Does NOT Exist

- ~~`tests/knowledge/__init__.py`~~ — does not exist and must **NOT** be created.
  Adding it changes import identity for the whole `tests/knowledge` subtree
  (including `tests/knowledge/wiki/`, which works through the namespace package
  today) and is explicitly out of scope.
- ~~`tests/conftest.py::_stub_if_absent`~~ — does not exist in the root tree.
  That helper belongs to `packages/ai-parrot/tests/conftest.py`.
- ~~`tests/test_conftest_stub_isolation.py`~~ — the root file is named
  `tests/test_stub_isolation.py` (no `conftest` in the name), because the root
  tree has no conftest stubs to guard.
- ~~`pytest.helpers` / a shared `tests/_support` module in the root tree~~ — the
  root `tests/` tree has no such helper package; the guard is self-contained.
- ~~`parrot.knowledge.pageindex.vector_walk` re-exported from the package
  `__init__`~~ — it is not; the guard resolves it by its full dotted name.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "tests/test_stub_isolation.py", "action": "CREATE"},
    {"path": "tests/knowledge/pageindex/__init__.py", "action": "CREATE"},
    {"path": ".github/workflows/ci.yml", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/test_conftest_stub_isolation.py#test_real_modules_are_not_shadowed",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py#NodeEmbeddingStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

`packages/ai-parrot/tests/test_conftest_stub_isolation.py` — same two-pronged
shape (a parametrized *live* check over `sys.modules`, plus a *static* source
scan that the originating pattern cannot reappear), same "Do not delete this
module" docstring convention. **Shape only**: the root tree's conftest installs
no stubs, so the three `_stub_if_absent` tests from that file have no root
counterpart and must not be copied.

### Key Constraints

- **No `parrot` import at module scope** in the guard. The live check must see
  whatever the modules collected *before* it did to `sys.modules`; importing at
  module scope would both pre-warm the entry and make the guard itself a
  participant in the problem it detects.
- The static scan reads source text — it must never `exec` or import a test
  module (importing every test module would be both slow and unsafe).
- The scan skips its own file, otherwise the pattern it searches for (which
  appears in its own regex literal) matches itself.
- Google-style docstrings, type hints, 120-column lines.

### References in Codebase

- `packages/ai-parrot/tests/test_conftest_stub_isolation.py:41-71` — the live
  check this file mirrors.
- `.github/workflows/ci.yml:610` — a job that deliberately omits
  `--continue-on-collection-errors`, with its reason in a comment: the house
  style for recording such a decision next to the flag.

---

## Implementation Blueprint

### Steps (in order)

1. Confirm TASK-5389 is `done` in the per-spec index. This guard **fails** against
   the pre-TASK-5389 tree (that is the point), so running it first produces a
   confusing red.
2. Create `tests/knowledge/pageindex/__init__.py` as an **empty** file — because
   the four modules must get `tests.knowledge.pageindex.*` identities before any
   full-tree run, so the same-named `test_embedding_store.py` in the packages
   twin can never collide with them.
3. Create `tests/test_stub_isolation.py` with the content below.
4. Add the `ci.yml` comment.
5. Prove the guard bites: temporarily re-insert a stub (the FILL IN item), watch
   `test_no_test_module_registers_a_parrot_stub` fail, then revert. A guard never
   observed failing is not known to guard anything (spec AC5).

### `tests/knowledge/pageindex/__init__.py` (CREATE)

```python
```

**Why this shape**: deliberately empty — a 0-byte package marker, exactly like
`packages/ai-parrot/tests/knowledge/pageindex/__init__.py` (also 0 bytes). It
carries no code because its only job is to give the four sibling modules a
package-qualified import name.

### `tests/test_stub_isolation.py` (CREATE)

```python
"""Regression guard: a root test module may not leave a real parrot module stubbed.

FEAT-852 / issue:91822a3b8548 — the root-tree counterpart of
``packages/ai-parrot/tests/test_conftest_stub_isolation.py`` (FEAT-617).

Four modules under ``tests/knowledge/pageindex/`` registered a bare stub for
``parrot.knowledge.pageindex`` in ``sys.modules`` so the package ``__init__``
would not run, then loaded submodules by file path. With ``__init__`` suppressed,
the package's own relative imports re-entered ``embedding_store`` while it was
still executing, leaving a half-built module behind: 6 collection errors, 2 red
wiki tests, and four test files silently skipped on every CI run.

The tell is always the same: a ``types.ModuleType`` stand-in has no ``__file__``.
Do not delete this module.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).parent

# Modules that are genuinely importable and have been observed stubbed in this tree.
MUST_NOT_BE_SHADOWED: tuple[str, ...] = (
    "parrot.knowledge.pageindex",
    "parrot.knowledge.pageindex.embedding_store",
    "parrot.knowledge.pageindex.hybrid_search",
    "parrot.knowledge.pageindex.toolkit",
    "parrot.knowledge.pageindex.vector_walk",
)

# `sys.modules[...] = ModuleType("parrot...")` in any form, and the setdefault
# variant FEAT-617 banned in the packages tree.
_STUB_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ModuleType\(\s*[\"']parrot"),
    re.compile(r"sys\.modules\.setdefault\(\s*[\"']parrot"),
)


@pytest.mark.parametrize("name", MUST_NOT_BE_SHADOWED)
def test_real_modules_are_not_shadowed(name: str) -> None:
    """A genuinely importable parrot module must resolve to a real file on disk.

    Runs in the live pytest process, so it sees whatever the modules collected
    before it have done to ``sys.modules``. A failure here names the poisoned module.
    """
    module = importlib.import_module(name)
    assert getattr(module, "__file__", None) is not None, (
        f"{name} resolved to a stand-in with no __file__ — a test module shadowed it and did "
        f"not restore it (see issue:91822a3b8548). Got {module!r}"
    )
    assert Path(module.__file__).exists(), f"{name}.__file__ does not exist on disk"
    assert sys.modules[name] is module, f"{name} is bound to a different object in sys.modules"


def test_no_test_module_registers_a_parrot_stub() -> None:
    """No file under tests/ may install a ModuleType stand-in for a parrot package.

    A static source scan: importing every test module to check would be both slow
    and unsafe. This file is skipped — the patterns appear in its own source.
    """
    offenders: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        if path == Path(__file__):
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in _STUB_PATTERNS:
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(TESTS_ROOT.parent)}:{line_no}: {match.group(0)}")
    assert not offenders, (
        "A stub for a real parrot package skips its __init__, so the package's own relative "
        "imports re-enter a half-built module (issue:91822a3b8548). Import the module normally "
        "instead. Offenders:\n  " + "\n  ".join(offenders)
    )
```

**Why this shape**: the live check is the FEAT-617 pattern verbatim (plus an
identity assertion, since a stub can also be installed *alongside* a real module
object). The static check is what makes the defect loud instead of a collection
error — it fails with file:line, in a job whose output is read, rather than
being swallowed by `--continue-on-collection-errors`. No `parrot` import at
module scope: the guard must observe `sys.modules`, not populate it.

### `.github/workflows/ci.yml` (MODIFY)

```yaml
# occurrences: 1 (verified: grep -c 'run: uv run pytest tests/ -q --tb=short --ignore=tests/tools --continue-on-collection-errors' .github/workflows/ci.yml)
# BEFORE — insert above `      - name: Run core tests` (verified: .github/workflows/ci.yml:311)
      # FEAT-852: `--continue-on-collection-errors` stays. It does not mask a red
      # job — collection errors already fail it — it only lets one run report
      # every failure instead of aborting at the first. The real gap was that a
      # never-collected file looked routine: four `tests/knowledge/pageindex/`
      # files were skipped on every run for months (issue:91822a3b8548).
      # `tests/test_stub_isolation.py` closes that gap directly, by failing loudly
      # with a file:line instead of leaving a silent skip.
```

**Why**: the issue asked for an explicit decision on this flag; recording it
beside the flag is the house style (see the converse note at `:610`, where a job
deliberately omits it). Comment only — the invocation itself must not change,
because removing the flag would report *less*, not more.

### FILL IN checklist

- [ ] `# FILL IN: prove the guard fails — temporarily add `import types, sys; sys.modules["parrot.knowledge.pageindex"] = types.ModuleType("parrot.knowledge.pageindex")` to one file under tests/, confirm `test_no_test_module_registers_a_parrot_stub` fails and names that file:line, then revert so the diff is clean. Bounded by AC5; record the observed failure message in the Completion Note.`
- [ ] `# FILL IN: confirm the scan's runtime is acceptable on the full root tests/ tree (it reads every .py once) — if `pytest tests/test_stub_isolation.py -q` exceeds ~5s, narrow rglob to the directories that have carried stubs rather than loosening the assertion. Bounded by: the check must still cover all of tests/.`

---

## Acceptance Criteria

- [ ] AC1 — `pytest tests/test_stub_isolation.py -q` passes (6 tests: 5
      parametrized + 1 scan).
- [ ] AC2 — `test_no_test_module_registers_a_parrot_stub` is demonstrated to
      **fail** when a stub is reintroduced, and the failure message names the
      offending `file:line`. Reverted afterwards; the observation is recorded in
      the Completion Note.
- [ ] AC3 — `tests/knowledge/pageindex/__init__.py` exists and is empty (0 bytes).
- [ ] AC4 — `pytest tests/knowledge/pageindex tests/knowledge/wiki tests/test_stub_isolation.py -q`
      passes, and so does the same command with the pageindex directory last.
- [ ] AC5 — `.github/workflows/ci.yml` carries the decision comment above
      `- name: Run core tests`, and `git diff .github/workflows/ci.yml` shows
      **added comment lines only** — no change to any `run:` line.
- [ ] AC6 — `ruff check tests/test_stub_isolation.py` is clean.
- [ ] AC7 — `tests/knowledge/__init__.py` was **not** created, and
      `packages/ai-parrot/tests/test_conftest_stub_isolation.py` was **not**
      modified.

---

## Validation Commands

- `pytest tests/test_stub_isolation.py -q`
- `pytest tests/knowledge/pageindex/test_embedding_store.py -q`
- `pytest tests/knowledge/wiki/test_cli_checkpoint.py -q`

> Run from the worktree with an **absolute** `PYTHONPATH` pointing at the
> worktree's `packages/ai-parrot/src`; a bare `pytest` imports the main checkout.
> AC4's order check needs the directories in one invocation.

---

## Test Specification

`tests/test_stub_isolation.py` is itself the test module; its full content is in
the blueprint. Expected collection:

```
tests/test_stub_isolation.py::test_real_modules_are_not_shadowed[parrot.knowledge.pageindex]
tests/test_stub_isolation.py::test_real_modules_are_not_shadowed[parrot.knowledge.pageindex.embedding_store]
tests/test_stub_isolation.py::test_real_modules_are_not_shadowed[parrot.knowledge.pageindex.hybrid_search]
tests/test_stub_isolation.py::test_real_modules_are_not_shadowed[parrot.knowledge.pageindex.toolkit]
tests/test_stub_isolation.py::test_real_modules_are_not_shadowed[parrot.knowledge.pageindex.vector_walk]
tests/test_stub_isolation.py::test_no_test_module_registers_a_parrot_stub
```

The negative case (AC2) is exercised by hand, not codified: codifying it would
mean writing a file that *contains* the banned pattern, which the scan would then
flag on every run.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-test-embedding-store-fixes --feature-id FEAT-852`)
2. **Read the spec** at `sdd/specs/pageindex-test-embedding-store-fixes.spec.md`
3. **Depends-on**: TASK-5389 must be `"done"` in
   `sdd/tasks/index/pageindex-test-embedding-store-fixes.json` — this guard is
   designed to fail against the pre-TASK-5389 tree.
4. **Verify the Codebase Contract** before writing code, especially the
   "Facts the guard depends on" list.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`),
   commit only that index file.
6. **Commit** only the three files:
   `fix(pageindex-test-embedding-store-fixes): TASK-5390 — root stub-isolation guard`
7. **Close** with `parrot sdd task close TASK-5390 pageindex-test-embedding-store-fixes verified`.

---

## Completion Note

<!-- Filled in by the implementing agent. -->
