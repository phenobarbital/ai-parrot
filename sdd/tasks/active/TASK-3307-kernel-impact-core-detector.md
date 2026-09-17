# TASK-3307: Test-scope kernel — import-impact selector + core detector

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3304, TASK-3305
**Assigned-to**: unassigned

---

## Context

Implements spec **Module 2 — Import-impact selector + core detector** (§2 Overview items 2 and 2b,
§3 Module 2, G7/G7b, R5/R15). The merge tier needs to add tests that *import* a changed source
module (mirror-of-directories alone misses them), and both merge and feature tiers must recognise
a **core** change — a module with transitive **source** fan-in ≥ 50 or listed in `CORE_PATHS` —
so the planner (TASK-3308) can escalate to the suites of every importing distribution.

Test-module counts are deliberately NOT the core signal: measured 2026-09-17,
`parrot.clients.base` has 182 source importers but 37 direct test importers, `parrot.bots.abstract`
146 vs 13 (spec §2 item 2b).

This module is part of the **stdlib-only** kernel core: it must import as
`parrot.flows.dev_loop.test_scope.impact` and as top-level `test_scope.impact`.

---

## Scope

- Implement `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py` with:
  - `module_name_for(path)` — `packages/<dist>/src/<top>/a/b.py` → `<top>.a.b` (`__init__.py` → package name);
    a `parrot/tools/<x>` source path also yields the alias `parrot_tools.<x>` (meta_path redirect).
  - `ImportIndex` dataclass: `by_module` (module → test files), `src_importers` (module → source modules
    importing it), `module_dist` (source module → distribution), `skipped` (unparseable files).
  - `ImportIndex.build(worktree)` — one AST pass over `tests/**/test_*.py`, `packages/*/tests/**/test_*.py`
    and `packages/*/src/**/*.py`; resolve relative imports for source modules; syntax errors → `skipped`.
  - `ImportIndex.load_or_build(worktree)` — JSON cache keyed by `git rev-parse HEAD^{tree}` in the
    per-worktree git dir obtained with `git rev-parse --absolute-git-dir` (do NOT import `context.py`:
    avoids an edge on TASK-3306).
  - `impacted_tests(index, changed, *, worktree, depth)` — direct importers + importers through ≤ `depth`
    source-module hops.
  - `source_fanin(index, module)` — transitive count of source importers + their distributions.
  - `detect_core(index, changed, *, policy)` — `CoreHit` per changed source file with fan-in ≥
    `policy.core_fanin_threshold` or path in `policy.core_paths`.
- Write unit tests in `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_impact.py` on tiny
  synthetic trees under `tmp_path`.

**NOT in scope**: tier orchestration / cap escalation / ledger dedupe (TASK-3308), editing `CORE_PATHS`
(TASK-3318), wikitoolkit blast radius (spec Non-Goal), any change to `policy.py` or `__init__.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py` | CREATE | AST import index, impacted tests, fan-in, core detection |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_impact.py` | CREATE | Unit tests on synthetic trees |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# stdlib only (kernel core — AC3). No parrot / pydantic imports in impact.py.
import ast
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Sequence
```

### Created by dependency tasks (verify on disk before use)
```python
# TASK-3304 — packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py
@dataclass(frozen=True)
class CoreHit:
    path: str; module: str; fanin: int; forced: bool; distributions: tuple[str, ...]
# TASK-3304 — test_scope/mirror.py
def distribution_of(path: str) -> str: ...   # '<dist>' for packages/<dist>/…, 'root' for tests/…; ValueError otherwise
# TASK-3305 — test_scope/policy.py
@dataclass(frozen=True)
class ScopePolicy:
    impact_cap: int; impact_depth: int; core_fanin_threshold: int; core_paths: tuple[str, ...]
    xdist_safe: frozenset[str]; marker_expression: str
```
Import them RELATIVELY: `from .datatypes import CoreHit`, `from .mirror import distribution_of`,
`from .policy import ScopePolicy`.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/__init__.py — sys.meta_path finder redirects
# parrot.tools.<x> → parrot_tools.<x> (CLAUDE.md "Tool-Centric Architecture"). Source files of the
# concrete tools live under packages/ai-parrot-tools/src/parrot_tools/<x>.
```
- Repo layout (verified 2026-09-17): test modules under `tests/` (490) and `packages/<dist>/tests/`;
  sources under `packages/<dist>/src/<top>/` where `<top>` is `parrot`, `parrot_tools`, `parrot_loaders`, `parrot_pipelines`, …
- Namespace satellites (PEP 420) have `src/parrot/` WITHOUT `__init__.py` — do not require `__init__.py`
  to recognise a package directory.

### Does NOT Exist
- ~~an `imports` relation in wikitoolkit blast radius~~ — do not call wikitoolkit; this module is the source of truth
- ~~`test_scope.context` helpers inside this task~~ — resolve the git dir yourself (`git rev-parse --absolute-git-dir`)
- ~~`parrot.flows.dev_loop.test_scope.impact`~~ — created by THIS task
- ~~a shared module-name helper elsewhere in dev_loop~~ — `module_name_for` is new here
- ~~`ScopePolicy.impact_cap` handling here~~ — the cap is applied by TASK-3308, not in `impacted_tests`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_impact.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
- Frozen/plain `@dataclass`, Google docstrings, full type hints, relative imports (see TASK-3304 `mirror.py`).
- Sync `subprocess.run([...], cwd=worktree, capture_output=True, text=True, check=False)` — the kernel is
  called from a hook process / CLI; async callers wrap it with `asyncio.to_thread` (spec §7).

### Key Constraints
- **stdlib only** — `test_core_is_stdlib_only` (TASK-3304) imports the whole package with `-I -S`.
- Never raise on a single bad file: record it in `skipped` (spec R5, plan notes).
- Cache failures (no git, unwritable dir, corrupt JSON) → silently rebuild; never fail planning.
- Fan-in is **transitive over source modules only**; distributions come from `module_dist`.
- A module listed in `policy.core_paths` is core even with fan-in below threshold (`forced=True`, R15).

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:588-717` — path conventions reused by the mirror (TASK-3304)
- `sdd/specs/scoped-test-selection.spec.md` §3 Module 2 skeleton — signatures are fixed

---

## Implementation Blueprint

### Steps (in order)
1. Create `impact.py` with the constants, `module_name_for`, and the `ImportIndex` dataclass — *why*: every other function consumes the index shape.
2. Implement `ImportIndex.build` (walk + `ast.parse` + import extraction + relative-import resolution) — *why*: single pass keeps the merge tier fast.
3. Implement `load_or_build` with the tree-id-keyed JSON cache — *why*: repeated merges on the same tree must not re-parse ~5k files.
4. Implement `impacted_tests`, `source_fanin`, `detect_core` — *why*: TASK-3308 composes exactly these three.
5. Write `test_impact.py` against a synthetic `tmp_path` tree (two dists + root tests) — *why*: AC9/AC9b logic without touching the real repo.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py` (CREATE)
```python
"""Import-impact selector and core detector (FEAT-563, spec Module 2).

Stdlib-only: one AST pass builds a reverse import index for test modules and
for source modules, used by the merge tier (impacted tests) and by the merge
and feature tiers (core detection by transitive source fan-in).
"""
from __future__ import annotations

import ast
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Sequence

from .datatypes import CoreHit
from .mirror import distribution_of
from .policy import ScopePolicy

INDEX_CACHE_PREFIX: str = "parrot-test-scope-index-"
_TOOLS_SRC_PREFIX: str = "packages/ai-parrot/src/parrot/tools/"


def module_name_for(path: str) -> str | None:
    """Map `packages/<dist>/src/<top>/a/b.py` to `<top>.a.b` (`__init__.py` → package).

    A `parrot/tools/<x>` source path yields its dotted name; callers that need the
    `parrot_tools.<x>` alias use `module_aliases`. Returns None for non-source paths.
    """
    parts = PurePosixPath(path).parts
    if len(parts) < 5 or parts[0] != "packages" or parts[2] != "src" or not path.endswith(".py"):
        return None
    dotted = list(parts[3:])
    dotted[-1] = dotted[-1][:-3]
    if dotted[-1] == "__init__":
        dotted.pop()
    return ".".join(dotted) or None


def module_aliases(module: str) -> tuple[str, ...]:
    """Return `module` plus its meta_path alias (`parrot.tools.x` ↔ `parrot_tools.x`)."""
    # FILL IN: return both spellings for parrot.tools.<x> / parrot_tools.<x>; other modules → (module,) — bounded by CLAUDE.md redirect rule
    raise NotImplementedError


@dataclass
class ImportIndex:
    """Reverse import index over one worktree."""

    by_module: dict[str, set[str]] = field(default_factory=dict)
    src_importers: dict[str, set[str]] = field(default_factory=dict)
    module_dist: dict[str, str] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    @classmethod
    def build(cls, worktree: Path) -> "ImportIndex":
        """Parse every test and source module under `worktree` once."""
        index = cls()
        # FILL IN: glob tests/**/test_*.py and packages/*/tests/**/test_*.py → record imported modules into by_module;
        #          glob packages/*/src/**/*.py → module_dist + src_importers (resolve `from . import x` via the file's package);
        #          ast.parse errors / UnicodeDecodeError → index.skipped.append(rel_path) — bounded by R5 (never raise)
        return index

    @classmethod
    def load_or_build(cls, worktree: Path) -> "ImportIndex":
        """Reuse a cache keyed by `git rev-parse HEAD^{tree}` in the per-worktree git dir."""
        # FILL IN: tree id + `git rev-parse --absolute-git-dir`; read/write INDEX_CACHE_PREFIX+<tree>.json
        #          (sets serialised as sorted lists); any failure → cls.build(worktree) — bounded by "cache never fails planning"
        return cls.build(worktree)


def impacted_tests(index: ImportIndex, changed: Sequence[str], *, worktree: Path, depth: int) -> list[str]:
    """Test files importing a changed module directly, or via ≤ `depth` source-module hops. Sorted."""
    # FILL IN: BFS over src_importers from each changed module (aliases included) up to `depth` hops,
    #          union by_module of every reached module; drop paths that no longer exist under worktree — bounded by AC9
    raise NotImplementedError


def source_fanin(index: ImportIndex, module: str) -> tuple[int, frozenset[str]]:
    """Transitive count of source modules importing `module`, and their distributions (incl. the module's own)."""
    # FILL IN: unbounded BFS with a visited set (cycles!) over src_importers — bounded by G7b "transitive"
    raise NotImplementedError


def detect_core(index: ImportIndex, changed: Sequence[str], *, policy: ScopePolicy) -> list[CoreHit]:
    """CoreHit per changed source file with fan-in ≥ threshold or listed in `policy.core_paths`."""
    hits: list[CoreHit] = []
    for path in changed:
        module = module_name_for(path)
        if module is None:
            continue
        fanin, dists = source_fanin(index, module)
        forced = path in policy.core_paths
        if forced or fanin >= policy.core_fanin_threshold:
            own = distribution_of(path)
            hits.append(CoreHit(path=path, module=module, fanin=fanin, forced=forced,
                                distributions=tuple(sorted(dists | {own}))))
    return hits
```
**Why this shape**: signatures follow the spec §3 Module 2 skeleton (fixed). `module_aliases` is a small
private-ish helper so the `parrot.tools` redirect is handled in one place (R15). `detect_core` is complete
because it is pure composition; the judgment lives in `build`, `impacted_tests` and `source_fanin`.

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_impact.py` (CREATE)
```python
"""Tests for test_scope.impact (FEAT-563 TASK-3307)."""
from __future__ import annotations

from pathlib import Path

from parrot.flows.dev_loop.test_scope.impact import (
    ImportIndex,
    detect_core,
    impacted_tests,
    module_name_for,
    source_fanin,
)
from parrot.flows.dev_loop.test_scope.policy import ScopePolicy


def _write(root: Path, rel: str, text: str = "") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _tree(tmp_path: Path) -> Path:
    """dist a: pa/base.py imported by pa/impl.py; dist b: pb/use.py imports pa.base."""
    _write(tmp_path, "packages/a/src/pa/__init__.py")
    _write(tmp_path, "packages/a/src/pa/base.py", "X = 1\n")
    _write(tmp_path, "packages/a/src/pa/impl.py", "from .base import X\n")
    _write(tmp_path, "packages/b/src/pb/use.py", "from pa.base import X\n")
    _write(tmp_path, "packages/a/tests/test_impl.py", "import pa.impl\n")
    _write(tmp_path, "packages/b/tests/test_use.py", "from pb import use\n")
    _write(tmp_path, "tests/test_root.py", "import pa.base\n")
    return tmp_path
```
**Why**: one shared synthetic tree exercises relative imports, cross-distribution fan-in and root tests.

### FILL IN checklist
- [ ] `impact.py::module_aliases` — both spellings for the tools redirect; bounded by CLAUDE.md redirect rule
- [ ] `impact.py::ImportIndex.build` — globs, AST extraction, relative-import resolution, skipped files; bounded by R5
- [ ] `impact.py::ImportIndex.load_or_build` — tree-id cache in per-worktree git dir; bounded by "never fails planning"
- [ ] `impact.py::impacted_tests` — depth-limited BFS; bounded by AC9 / `DEFAULT_IMPACT_DEPTH`
- [ ] `impact.py::source_fanin` — transitive, cycle-safe; bounded by G7b
- [ ] `test_impact.py` — test bodies listed in Test Specification

---

## Acceptance Criteria

- [ ] `module_name_for` maps src-layout paths (incl. `__init__.py`) and returns None elsewhere; the `parrot.tools` alias is honoured (spec §4 `test_module_name_for_src_layout_and_tools_redirect`)
- [ ] Direct importers found; a 2-hop importer excluded at depth 1 (`test_impacted_tests_direct_and_one_hop`)
- [ ] Core detected by **source** fan-in even with few test importers; `CORE_PATHS` forces a hit; distributions include every importing dist (AC9b logic)
- [ ] Broken test module listed in `skipped`, never raises (`test_index_skips_syntax_errors`)
- [ ] `impact.py` imports only stdlib + relative kernel modules (AC3)
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py` clean

---

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_impact.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_scope/test_impact.py (continued)
def test_module_name_for_src_layout_and_tools_redirect():
    assert module_name_for("packages/a/src/pa/base.py") == "pa.base"
    assert module_name_for("packages/a/src/pa/__init__.py") == "pa"
    assert module_name_for("docs/x.py") is None


def test_impacted_tests_direct_and_one_hop(tmp_path):
    root = _tree(tmp_path)
    index = ImportIndex.build(root)
    direct = impacted_tests(index, ["packages/a/src/pa/base.py"], worktree=root, depth=0)
    assert "tests/test_root.py" in direct
    one_hop = impacted_tests(index, ["packages/a/src/pa/base.py"], worktree=root, depth=1)
    assert {"packages/a/tests/test_impl.py", "packages/b/tests/test_use.py"} <= set(one_hop)


def test_core_detected_by_source_fanin_not_test_count(tmp_path):
    root = _tree(tmp_path)
    hits = detect_core(ImportIndex.build(root), ["packages/a/src/pa/base.py"],
                       policy=ScopePolicy(core_fanin_threshold=2, core_paths=()))
    assert hits and hits[0].distributions == ("a", "b")


def test_core_paths_force_escalation(tmp_path):
    root = _tree(tmp_path)
    hits = detect_core(ImportIndex.build(root), ["packages/a/src/pa/impl.py"],
                       policy=ScopePolicy(core_fanin_threshold=999, core_paths=("packages/a/src/pa/impl.py",)))
    assert hits[0].forced is True


def test_source_fanin_is_cycle_safe(tmp_path):
    ...  # FILL IN: two modules importing each other → finite count


def test_index_skips_syntax_errors(tmp_path):
    ...  # FILL IN: tests/test_broken.py with "def (" → in index.skipped, build does not raise
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3307-kernel-impact-core-detector.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
