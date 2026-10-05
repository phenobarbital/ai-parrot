# TASK-4085: SDD helpers move A: ledger/worktree helpers into parrot.sdd.scripts

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4070
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6: "The 18 doc-referenced helpers (…) move to `parrot/sdd/scripts/`;
ALL markdown (installed AND monorepo) references the single form
`python -m parrot.sdd.scripts.<name>` …; `scripts/sdd/*.py` become thin wrappers (import +
main) for direct-invocation compatibility". The spec §5 acceptance bullet requires that
"`scripts/sdd/` wrappers keep the monorepo's existing invocations working".

This is the first of four move tasks. It creates the `parrot.sdd.scripts` package and
moves the **ID-ledger and worktree** helpers: `id_ledger`, `reserve_ids`,
`check_id_collisions`, `ensure_worktree`. It also adds `parrot.sdd.scripts.sdd_meta`, a
re-export of `parrot.knowledge.wiki.ledger.sdd_meta`, so every moved module can import
`sdd_meta` from inside the package. `scripts/sdd/sdd_meta.py` itself is **already** a
re-export shim (the precedent) and is **not changed**.

> ⚠️ **LIVE INFRASTRUCTURE.** `reserve_ids` and `ensure_worktree` are run concurrently by
> other sessions (`/sdd-spec`, `/sdd-task`, `/sdd-start`, `sdd-worker`, the dev-loop
> orchestrators). The `scripts/sdd/` shim must keep `python -m scripts.sdd.reserve_ids …`
> and `python -m scripts.sdd.ensure_worktree …` **byte-for-byte identical**: the same
> stdout lines, stderr, exit codes and argparse `--help` text. **Never change their CLI**:
> no renamed or added flags, no changed `prog=`/`description=`, no reworded output. The
> moved file must differ from the original ONLY in the import lines listed in the
> blueprint.

---

## Scope

- Create `parrot/sdd/scripts/__init__.py` (docstring only, no imports).
- Create `parrot/sdd/scripts/sdd_meta.py`, re-exporting the same 15 names as
  `scripts/sdd/sdd_meta.py`.
- Move `id_ledger.py`, `reserve_ids.py`, `check_id_collisions.py` and
  `ensure_worktree.py` from `scripts/sdd/` to `packages/ai-parrot/src/parrot/sdd/scripts/`
  **with `git mv`** to keep history. Then rewrite only their `from scripts.sdd…` import
  lines.
- Recreate each `scripts/sdd/<name>.py` as the alias shim. The module object becomes
  identical to the moved module, so existing tests that monkeypatch private names keep
  working.
- Add `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py`.

**NOT in scope**:
- Moving any other helper (TASK-4086/4087/4088).
- Rewriting markdown references (TASK-4089).
- Docstring `Usage:` lines that still say `python -m scripts.sdd.<name>` (e.g.
  `id_ledger.py:14,176`, `reserve_ids.py:22`, `check_id_collisions.py:18`,
  `ensure_worktree.py:6`). Leave them. They are not CLI behaviour, and TASK-4089 owns the
  reference rewrite.
- Changing `scripts/sdd/sdd_meta.py` or `scripts/sdd/__init__.py`.
- Changing any test under `tests/sdd_scripts/`. The shim keeps them passing unmodified.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/__init__.py` | CREATE | Package marker; docstring only |
| `packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py` | CREATE | Re-export of `parrot.knowledge.wiki.ledger.sdd_meta` |
| `packages/ai-parrot/src/parrot/sdd/scripts/id_ledger.py` | CREATE | `git mv` of `scripts/sdd/id_ledger.py` (no line changes) |
| `packages/ai-parrot/src/parrot/sdd/scripts/reserve_ids.py` | CREATE | `git mv` of `scripts/sdd/reserve_ids.py` + 1 import rewrite |
| `packages/ai-parrot/src/parrot/sdd/scripts/check_id_collisions.py` | CREATE | `git mv` of `scripts/sdd/check_id_collisions.py` (no line changes) |
| `packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py` | CREATE | `git mv` of `scripts/sdd/ensure_worktree.py` + 1 import rewrite |
| `scripts/sdd/id_ledger.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/reserve_ids.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/check_id_collisions.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/ensure_worktree.py` | MODIFY | Becomes alias shim |
| `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py` | CREATE | Importability, `-m --help`, shim identity, help parity |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# re-export source (all verified in packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py)
from parrot.knowledge.wiki.ledger.sdd_meta import (
    KNOWN_BRANCHES,   # :30
    WORK_KIND_FLOW,   # :35
    KNOWN_PROJECTS,   # :45
    PROJECT_ALIASES,  # :84
    FlowMeta,         # :99
    parse,            # :129
    emit,             # :156
    normalize_tag,    # :173
    normalize_project,# :188
    DocTaxonomy,      # :218
    parse_taxonomy,   # :247
    resolve_flow,     # :263
    WORKTREE_ROOT,    # :322
    WorktreePlan,     # :328
    plan_worktree,    # :336
)
# sdd_meta's own third-party imports: yaml (:20), pydantic (:21) — both core deps
# (packages/ai-parrot/pyproject.toml: "pydantic==2.12.5", "PyYAML>=6.0.2").
# Importing it is light: 0.16 s, no navconfig, no chdir (verified 2026-10-05).
```

### Existing Signatures to Use
```python
# scripts/sdd/sdd_meta.py (26 lines) — the PRECEDENT re-export shim; re-exports exactly the 15 names above,
# lines 10-26 `from parrot.knowledge.wiki.ledger.sdd_meta import (  # noqa: F401 ... )`. NOT modified.

# scripts/sdd/id_ledger.py (220 lines)
LEDGER_PATH = Path("sdd/tasks/.id_ledger.json")                     # :28  (cwd-relative — fine, not __file__)
def main(argv: list[str] | None = None) -> int:                      # :175 (subparsers required=True :180)
if __name__ == "__main__": raise SystemExit(main())                  # :219-220
#   third-party: `from pydantic import BaseModel, Field` (:25) — core. No __file__/parents[/subprocess.

# scripts/sdd/reserve_ids.py (657 lines)
from scripts.sdd.id_ledger import LEDGER_PATH, IdLedger, save_ledger  # :42  ← REWRITE
def main(argv: list[str] | None = None) -> int:                      # :616 (ArgumentParser :626, no prog=)
if __name__ == "__main__": raise SystemExit(main())                  # :656-657
#   subprocess: git only, via subprocess.run at :121 (no scripts/sdd or `-m scripts.sdd` spawn).
#   repo root: `root = repo_root if repo_root is not None else Path.cwd()` (:541) — cwd, fine.
#   third-party: `from pydantic import BaseModel, Field, ValidationError` (:40) — core.
#   No __file__ / parents[.

# scripts/sdd/check_id_collisions.py (327 lines)
def main(argv: list[str] | None = None) -> int:                      # :254 (ArgumentParser :264, no prog=)
if __name__ == "__main__": raise SystemExit(main())                  # :326-327
#   defaults cwd-relative Path("sdd/tasks/index") etc. (:82-85, :267-270). pydantic (:30) — core.
#   No inter-import, no __file__, no subprocess.

# scripts/sdd/ensure_worktree.py (324 lines)
from scripts.sdd.sdd_meta import WorktreePlan, plan_worktree, resolve_flow  # :20 ← REWRITE
def main(argv: Sequence[str] | None = None) -> int:                  # :225 (ArgumentParser :233, no prog=)
    repo_root = Path.cwd()                                            # :288 — cwd, fine
if __name__ == "__main__":  # pragma: no cover                       # :323-324 raise SystemExit(main())
#   subprocess: git only (:31). Stdlib + sdd_meta only. No __file__ / parents[.

# Existing tests that must keep passing through the shim (all verified to exist):
#   tests/sdd_scripts/test_id_ledger.py           (from scripts.sdd.id_ledger import IdLedger, bootstrap_ledger, …  :7)
#   tests/sdd_scripts/test_reserve_ids.py         (monkeypatches subprocess.run globally :151)
#   tests/sdd_scripts/test_check_id_collisions.py (imports private _id_sort_key :225)
#   tests/sdd_scripts/test_ensure_worktree.py     (from scripts.sdd.ensure_worktree import EnsureWorktreeError, ensure, main :11)
#   tests/sdd_scripts/test_sdd_meta.py, tests/sdd_scripts/test_worktree_plan.py (sdd_meta shim — unchanged)
```

### Does NOT Exist
- ~~`parrot.sdd.scripts`~~ — created here. `parrot/sdd/__init__.py` comes from TASK-4070.
- ~~`parrot.sdd.scripts.close_task` / `heal_orphans`~~ — TASK-4087. Never import them here.
- ~~A `prog=` argument on the reserve_ids / ensure_worktree / id_ledger /
  check_id_collisions parsers~~ — none exists. Help text derives `prog` from
  `sys.argv[0]`'s basename, which is the same (`<name>.py`) for both
  `-m scripts.sdd.<name>` and `-m parrot.sdd.scripts.<name>`. Keep it that way.
- ~~Any `__file__`-based repo-root derivation in these four modules~~ — none (grep-verified).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/id_ledger.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/reserve_ids.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/check_id_collisions.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py", "action": "CREATE"},
    {"path": "scripts/sdd/id_ledger.py", "action": "MODIFY"},
    {"path": "scripts/sdd/reserve_ids.py", "action": "MODIFY"},
    {"path": "scripts/sdd/check_id_collisions.py", "action": "MODIFY"},
    {"path": "scripts/sdd/ensure_worktree.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#FlowMeta",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#parse",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#emit",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#normalize_tag",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#normalize_project",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#DocTaxonomy",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#parse_taxonomy",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#resolve_flow",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#WorktreePlan",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#plan_worktree",
    "sym:scripts/sdd/id_ledger.py#main",
    "sym:scripts/sdd/reserve_ids.py#main",
    "sym:scripts/sdd/check_id_collisions.py#main",
    "sym:scripts/sdd/ensure_worktree.py#main"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# scripts/sdd/sdd_meta.py — existing re-export shim (precedent for "implementation lives in the wheel").
# Alias shim pattern (fixed by the FEAT-633 task brief):
"""Compatibility shim — moved to ``parrot.sdd.scripts.<name>`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import <name> as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### Key Constraints
- **`git mv` first, then edit.** This keeps `git log --follow` history. Never retype or
  copy a moved file.
- The moved file differs from the original **only** in the lines the blueprint lists.
  `git diff -M --stat` must show a rename with a near-100% similarity index.
- The shim replaces `sys.modules["scripts.sdd.<name>"]` with the package module. Then
  `from scripts.sdd.<name> import _private`, `monkeypatch.setattr(mod, …)` and
  `patch("scripts.sdd.<name>.X")` all hit the real module. When run as `__main__`, the shim
  calls `_impl.main()` before the alias line, which is harmless.
- **Worktree gotcha.** The shared `.venv` is editable-installed against the MAIN
  checkout, which has no `parrot.sdd` until this feature merges. Inside the FEAT-633
  worktree, `python -m scripts.sdd.reserve_ids …` therefore only works with
  `PYTHONPATH=packages/ai-parrot/src`. Primary-checkout invocations
  (`python -m scripts.sdd.ensure_worktree …` from the main repo, used by every other
  session) keep running the old, unmoved code until merge, so they are unaffected.
- Run `ruff check` on every moved file. The global `ruff.toml` rules apply equally to
  `scripts/` and `packages/`, so no new lint findings are expected.

### References in Codebase
- `scripts/sdd/sdd_meta.py` — precedent shim.
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` — re-export source.

---

## Implementation Blueprint

### Steps (in order)
1. `mkdir -p packages/ai-parrot/src/parrot/sdd/scripts`, then write `__init__.py` and
   `sdd_meta.py`. *Why*: the moved modules import `parrot.sdd.scripts.sdd_meta`.
2. `git mv` the four files:
   `git mv scripts/sdd/{id_ledger,reserve_ids,check_id_collisions,ensure_worktree}.py packages/ai-parrot/src/parrot/sdd/scripts/`
   (one `git mv` per file). *Why*: this preserves history.
3. Apply the two import rewrites (reserve_ids, ensure_worktree). *Why*: the package must
   never import the repo-local `scripts` package, which is absent from the wheel.
4. Commit the rename on its own (moved files + `__init__.py` + `sdd_meta.py`) before
   writing the shims. *Why*: git rename detection stays at 100% and the shims show as new
   content.
5. Write the four shims at the original paths. *Why*: existing `python -m scripts.sdd.*`
   invocations and `tests/sdd_scripts/` must keep working.
6. Write the test file and run the Validation Commands. *Why*: they prove the alias and
   the byte-identical help output.

### `packages/ai-parrot/src/parrot/sdd/scripts/__init__.py` (CREATE)
```python
"""SDD helper scripts, invocable as ``python -m parrot.sdd.scripts.<name>`` (FEAT-633).

The repo-local ``scripts/sdd/<name>.py`` files are compatibility shims aliasing these modules.
Intentionally import-free.
"""
```

### `packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py` (CREATE)
```python
"""Re-export of :mod:`parrot.knowledge.wiki.ledger.sdd_meta` for in-package SDD helpers (FEAT-633).

Same names as the repo-local ``scripts/sdd/sdd_meta.py`` shim, so moved helpers import
``from parrot.sdd.scripts.sdd_meta import …`` without touching the repo-local ``scripts`` package.
"""

from parrot.knowledge.wiki.ledger.sdd_meta import (  # noqa: F401
    KNOWN_BRANCHES,
    KNOWN_PROJECTS,
    PROJECT_ALIASES,
    WORK_KIND_FLOW,
    WORKTREE_ROOT,
    DocTaxonomy,
    FlowMeta,
    WorktreePlan,
    emit,
    normalize_project,
    normalize_tag,
    parse,
    parse_taxonomy,
    plan_worktree,
    resolve_flow,
)
```

### `packages/ai-parrot/src/parrot/sdd/scripts/id_ledger.py` (CREATE)
```python
# git mv scripts/sdd/id_ledger.py packages/ai-parrot/src/parrot/sdd/scripts/id_ledger.py
# No line changes: id_ledger has no scripts.sdd import, no __file__, no subprocess (verified).
```

### `packages/ai-parrot/src/parrot/sdd/scripts/reserve_ids.py` (CREATE)
```python
# git mv scripts/sdd/reserve_ids.py packages/ai-parrot/src/parrot/sdd/scripts/reserve_ids.py, then:
# occurrences: 1 (verified: grep -c 'from scripts.sdd.id_ledger import LEDGER_PATH, IdLedger, save_ledger' scripts/sdd/reserve_ids.py)
# REPLACE — `from scripts.sdd.id_ledger import LEDGER_PATH, IdLedger, save_ledger` (verified: scripts/sdd/reserve_ids.py:42)
from parrot.sdd.scripts.id_ledger import LEDGER_PATH, IdLedger, save_ledger
```

### `packages/ai-parrot/src/parrot/sdd/scripts/check_id_collisions.py` (CREATE)
```python
# git mv scripts/sdd/check_id_collisions.py packages/ai-parrot/src/parrot/sdd/scripts/check_id_collisions.py
# No line changes (no scripts.sdd import, no __file__, no subprocess — verified).
```

### `packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py` (CREATE)
```python
# git mv scripts/sdd/ensure_worktree.py packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py, then:
# occurrences: 1 (verified: grep -c 'from scripts.sdd.sdd_meta import WorktreePlan, plan_worktree, resolve_flow' scripts/sdd/ensure_worktree.py)
# REPLACE — `from scripts.sdd.sdd_meta import WorktreePlan, plan_worktree, resolve_flow` (verified: scripts/sdd/ensure_worktree.py:20)
from parrot.sdd.scripts.sdd_meta import WorktreePlan, plan_worktree, resolve_flow
```

### `scripts/sdd/id_ledger.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""``IdLedger`` model + bootstrap for the git-native TASK/FEAT ID allocator.' scripts/sdd/id_ledger.py)
# REPLACE — whole file (the original moved away via git mv; recreate the path with exactly this content);
#           first line was `"""``IdLedger`` model + bootstrap for the git-native TASK/FEAT ID allocator.` (verified: scripts/sdd/id_ledger.py:1)
"""Compatibility shim — moved to ``parrot.sdd.scripts.id_ledger`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import id_ledger as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `scripts/sdd/reserve_ids.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""``reserve_ids.py`` — the git-native compare-and-swap TASK/FEAT ID allocator.' scripts/sdd/reserve_ids.py)
# REPLACE — whole file; first line was `"""``reserve_ids.py`` — the git-native compare-and-swap TASK/FEAT ID allocator.`
#           (verified: scripts/sdd/reserve_ids.py:1). original main: `def main(argv: list[str] | None = None) -> int:` (:616)
"""Compatibility shim — moved to ``parrot.sdd.scripts.reserve_ids`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import reserve_ids as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `scripts/sdd/check_id_collisions.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""``check_id_collisions.py`` — defense-in-depth SDD ID collision scanner.' scripts/sdd/check_id_collisions.py)
# REPLACE — whole file; first line was `"""``check_id_collisions.py`` — defense-in-depth SDD ID collision scanner.`
#           (verified: scripts/sdd/check_id_collisions.py:1). original main: `def main(argv: list[str] | None = None) -> int:` (:254)
"""Compatibility shim — moved to ``parrot.sdd.scripts.check_id_collisions`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import check_id_collisions as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `scripts/sdd/ensure_worktree.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""Idempotent feature/hotfix worktree provisioning for SDD commands (FEAT-552).' scripts/sdd/ensure_worktree.py)
# REPLACE — whole file; first line was `"""Idempotent feature/hotfix worktree provisioning for SDD commands (FEAT-552).`
#           (verified: scripts/sdd/ensure_worktree.py:1). original main: `def main(argv: Sequence[str] | None = None) -> int:` (:225)
"""Compatibility shim — moved to ``parrot.sdd.scripts.ensure_worktree`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import ensure_worktree as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py` (CREATE)
See **Test Specification**. That block is the starting file.

### FILL IN checklist
- [ ] None in production code: every change is mechanical (`git mv` + two import lines +
  four fixed shims).
- [ ] `test_scripts_ledger_worktree.py`: confirm `--help` parity holds on the
  interpreter in use. Python 3.14 changed argparse's default `prog` for `-m`; the venv is
  3.12.3. If parity breaks on a newer interpreter, report it and do NOT add `prog=`
  (bounded by the "never change their CLI" warning).

---

## Acceptance Criteria

- [ ] AC-1: `python -m parrot.sdd.scripts.<name> --help` exits 0 for `id_ledger`,
  `reserve_ids`, `check_id_collisions`, `ensure_worktree`, run from a non-repo cwd.
- [ ] AC-2: `import scripts.sdd.<name>` yields the very same module object as
  `parrot.sdd.scripts.<name>` for the four moved modules.
- [ ] AC-3: `python -m scripts.sdd.reserve_ids --help` and
  `python -m scripts.sdd.ensure_worktree --help` stdout are byte-identical to the
  `parrot.sdd.scripts` invocations. Exit codes for a usage error (missing required flag)
  are identical (2).
- [ ] AC-4: `parrot.sdd.scripts.sdd_meta.<name> is parrot.knowledge.wiki.ledger.sdd_meta.<name>`
  for all 15 names. `scripts/sdd/sdd_meta.py` is unchanged (`git diff` empty).
- [ ] AC-5: The existing suites pass unmodified (see Validation Commands).
- [ ] AC-6: `git log --follow packages/ai-parrot/src/parrot/sdd/scripts/reserve_ids.py`
  shows the pre-move history.
- [ ] AC-7: `ruff check packages/ai-parrot/src/parrot/sdd/scripts scripts/sdd packages/ai-parrot/tests/sdd`
  is clean.
- [ ] Spec §5: "`scripts/sdd/` wrappers keep the monorepo's existing invocations working"
  (for these four).

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py -q`
- `pytest tests/sdd_scripts/test_id_ledger.py -q`
- `pytest tests/sdd_scripts/test_reserve_ids.py -q`
- `pytest tests/sdd_scripts/test_check_id_collisions.py -q`
- `pytest tests/sdd_scripts/test_ensure_worktree.py -q`
- `pytest tests/sdd_scripts/test_sdd_meta.py -q`
- `pytest tests/sdd_scripts/test_worktree_plan.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py
"""FEAT-633 move A: ledger/worktree helpers live in parrot.sdd.scripts; scripts/sdd shims alias them."""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC = REPO_ROOT / "packages" / "ai-parrot" / "src"
MOVED = ("id_ledger", "reserve_ids", "check_id_collisions", "ensure_worktree")
SDD_META_NAMES = (
    "KNOWN_BRANCHES", "KNOWN_PROJECTS", "PROJECT_ALIASES", "WORK_KIND_FLOW", "WORKTREE_ROOT", "DocTaxonomy",
    "FlowMeta", "WorktreePlan", "emit", "normalize_project", "normalize_tag", "parse", "parse_taxonomy",
    "plan_worktree", "resolve_flow",
)


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(SRC), str(REPO_ROOT), env.get("PYTHONPATH", "")])
    return env


def _run(module: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", module, *args], cwd=cwd, env=_env(), capture_output=True, text=True)


@pytest.mark.parametrize("name", (*MOVED, "sdd_meta"))
def test_importable_from_package(name: str) -> None:
    assert importlib.import_module(f"parrot.sdd.scripts.{name}") is not None


@pytest.mark.parametrize("name", MOVED)
def test_module_help_from_foreign_cwd(name: str, tmp_path: Path) -> None:
    assert _run(f"parrot.sdd.scripts.{name}", "--help", cwd=tmp_path).returncode == 0


@pytest.mark.parametrize("name", MOVED)
def test_shim_aliases_package_module(name: str) -> None:
    assert importlib.import_module(f"scripts.sdd.{name}") is importlib.import_module(f"parrot.sdd.scripts.{name}")


@pytest.mark.parametrize("name", ("reserve_ids", "ensure_worktree"))
def test_live_cli_help_and_usage_error_unchanged(name: str) -> None:
    shim, pkg = _run(f"scripts.sdd.{name}", "--help", cwd=REPO_ROOT), _run(f"parrot.sdd.scripts.{name}", "--help", cwd=REPO_ROOT)
    assert (shim.returncode, shim.stdout) == (pkg.returncode, pkg.stdout)
    assert _run(f"scripts.sdd.{name}", cwd=REPO_ROOT).returncode == _run(f"parrot.sdd.scripts.{name}", cwd=REPO_ROOT).returncode == 2


def test_sdd_meta_reexport_identity() -> None:
    pkg = importlib.import_module("parrot.sdd.scripts.sdd_meta")
    src = importlib.import_module("parrot.knowledge.wiki.ledger.sdd_meta")
    for name in SDD_META_NAMES:
        assert getattr(pkg, name) is getattr(src, name), name
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**. Never work on `base_branch`.
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context.
3. **Check dependencies**: every `Depends-on` task must be `"done"` in the per-spec index
   `sdd/tasks/index/parrot-installer.json`.
4. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source).
   - Confirm every class/method in "Existing Signatures" still has the listed attributes.
   - If anything has changed, update the contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without
     verifying it exists.
5. **Update status** in `sdd/tasks/index/parrot-installer.json` to `"in-progress"` (set
   `started_at`) and commit only that index file.
6. **Implement**. Start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes.
7. **Verify** that all acceptance criteria are met by running the Validation Commands.
8. **Commit the code**. Stage only the files this task lists (never `git add .` / `-A`).
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4085 parrot-installer verified`.
   It moves this file to `sdd/tasks/completed/` and marks it `"done"` in the index. Never
   move or copy the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
