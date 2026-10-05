# TASK-4086: SDD helpers move B1: task-state helpers into parrot.sdd.scripts

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4085
**Assigned-to**: unassigned

---

## Context

This task implements part of spec §3 Module 6, which says the doc-referenced helpers
"move to `parrot/sdd/scripts/`" and that "`scripts/sdd/*.py` become thin wrappers (import
+ main) for direct-invocation compatibility". It also serves the spec §5 bullet:
"`scripts/sdd/` wrappers keep the monorepo's existing invocations working".

This is move **B1**, the task-state helpers: `finalize_task`, `check_task_state`,
`check_task_graph` and `worktree_status`. They are used by `/sdd-start`, `/sdd-done`,
`/sdd-task`, `/sdd-next`, `/sdd-status` and the `sdd-worker` orchestrator. TASK-4085 has
already created `parrot/sdd/scripts/` (with `__init__.py`) and the
`parrot.sdd.scripts.sdd_meta` re-export used below. The mechanics are the same as
TASK-4085: `git mv` each file, rewrite only the lines listed in the blueprint, and turn
the old path into the alias shim.

Two of these modules need more than an import rewrite:

- **`check_task_graph`** builds a path from its own file location
  (`Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"`).
  Inside site-packages that path would point at nothing. After the move, the kernel is a
  **sibling inside the same `parrot` package**, so the path becomes package-relative.
  This is the correct form for an installed wheel. It does not derive a repository root.
- **`finalize_task`** calls `repo_root / "scripts" / "sdd" / "close_task.sh"` (line 394).
  It derives `repo_root` from git (`_git_toplevel`, line 115), not from `__file__`, so
  it keeps working in the monorepo. In a foreign repo it would fail with
  `OperationError("close_task.sh not found …")`. **Leave line 394 unchanged in this
  task.** `parrot.sdd.scripts.close_task` does not exist until TASK-4087, and this task
  must not reference it. The foreign-repo fix (spawning
  `sys.executable -m parrot.sdd.scripts.close_task`) is a follow-up that needs an owner.
  Record it in the Completion Note.

---

## Scope

- `git mv` `finalize_task.py`, `check_task_state.py`, `check_task_graph.py` and
  `worktree_status.py` into `packages/ai-parrot/src/parrot/sdd/scripts/`.
- Rewrite the `worktree_status` import (and the comment line above it) to use
  `parrot.sdd.scripts.sdd_meta`.
- Make the `check_task_graph` `_KERNEL_DIR` path package-relative.
- Recreate the four `scripts/sdd/<name>.py` files as alias shims.
- Add `packages/ai-parrot/tests/sdd/test_scripts_task_state.py`.

**NOT in scope**:
- `close_task.sh` / `heal_orphans.sh` (TASK-4087).
- `finalize_task.py:394`, which still looks up `scripts/sdd/close_task.sh` (see Context:
  a follow-up).
- Docstring/usage strings that mention `scripts/sdd/...` or `python -m scripts.sdd...`,
  including `finalize_task.py:598`
  `prog="python -m scripts.sdd.finalize_task"` and the remediation hint at
  `check_task_state.py:196-197`. Those strings are user-visible CLI output, and TASK-4089
  owns reference rewrites. Leave them byte-identical.
- Making `finalize_task`'s module-level `parrot.flows.dev_loop.sdd_coder.*` imports
  lazy. Today they take about 2.4 s and pull in navconfig, which `os.chdir`s on import.
  That behaviour already exists. Record it; do not change it.
- `scripts/sdd/__init__.py` and the `tests/sdd_scripts/` suite: unchanged.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py` | CREATE | `git mv` of `scripts/sdd/finalize_task.py` (no line changes) |
| `packages/ai-parrot/src/parrot/sdd/scripts/check_task_state.py` | CREATE | `git mv` of `scripts/sdd/check_task_state.py` (no line changes) |
| `packages/ai-parrot/src/parrot/sdd/scripts/check_task_graph.py` | CREATE | `git mv` + package-relative `_KERNEL_DIR` |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py` | CREATE | `git mv` + `sdd_meta` import rewrite |
| `scripts/sdd/finalize_task.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/check_task_state.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/check_task_graph.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/worktree_status.py` | MODIFY | Becomes alias shim (`main()` takes no argv) |
| `packages/ai-parrot/tests/sdd/test_scripts_task_state.py` | CREATE | Importability, `-m --help`, shim identity, kernel path |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.sdd.scripts.sdd_meta import WORKTREE_ROOT  # created by TASK-4085 (re-exports
                                                       # parrot/knowledge/wiki/ledger/sdd_meta.py:322)
# finalize_task's existing parrot imports (unchanged, all core ai-parrot):
from parrot.flows.dev_loop.sdd_coder.fidelity import check_fidelity, parse_task_files                    # finalize_task.py:49
from parrot.flows.dev_loop.sdd_coder.optimization_models import EvidenceRef, TaskCompletionEvidence      # finalize_task.py:50
from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root                                # finalize_task.py:51
# third-party in all four modules: pydantic only — core dep ("pydantic==2.12.5")
```

### Existing Signatures to Use
```python
# scripts/sdd/finalize_task.py (629 lines)
try:  # POSIX only -- degrades to a no-op lock  ...  import fcntl ... fcntl = None   # :53-56 (unchanged)
def _git_toplevel(worktree: Path) -> Path:                     # :115 — repo root via `git rev-parse --show-toplevel`
def _close_task_isolated(repo_root: Path, task_id: str, feature_slug: str) -> tuple[list[str], list[str]]:  # :375
    close_script = repo_root / "scripts" / "sdd" / "close_task.sh"   # :394  ← repo-layout assumption, LEFT AS IS
    ["bash", str(close_script), task_id, feature_slug, _VERIFICATION]  # :423 (subprocess, env GIT_INDEX_FILE)
def main(argv: list[str] | None = None) -> int:                # :596 — prog="python -m scripts.sdd.finalize_task" (:598)
if __name__ == "__main__": raise SystemExit(main())            # :628-629
#   No scripts.sdd import. No __file__.

# scripts/sdd/check_task_state.py (205 lines)
def main(argv: list[str] | None = None) -> int:                # :163 (cwd-relative defaults :173-175)
if __name__ == "__main__": raise SystemExit(main())            # :204-205
#   No inter-import, no __file__, no subprocess. Hint strings at :196-197 mention scripts/sdd/*.sh (unchanged).

# scripts/sdd/check_task_graph.py (461 lines)
_KERNEL_DIR = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"  # :59  ← REWRITE
def _load_contract():  # :198 — inserts _KERNEL_DIR on sys.path, importlib.import_module("test_scope.contract")
def main(argv: list[str] | None = None) -> int:                # :445 (--root default Path(".") :449)
if __name__ == "__main__": raise SystemExit(main())            # :460-461
# Kernel exists: packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/{__init__,contract,...}.py

# scripts/sdd/worktree_status.py (718 lines)
# scripts/sdd/sdd_meta.py is a re-export shim; the definition lives in the package.   # :20 ← REWRITE (comment)
from scripts.sdd.sdd_meta import (  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:322  # :21 ← REWRITE
    WORKTREE_ROOT,                                                                      # :22
)                                                                                       # :23
def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:   # :86 (git only)
def main() -> int:                                             # :614 — NO argv parameter; argparse reads sys.argv (:623-637)
    repo_root_proc = _git("rev-parse", "--show-toplevel", cwd=Path.cwd())   # :640 — git discovery, fine
if __name__ == "__main__": sys.exit(main())                    # :717-718

# Existing tests that must keep passing through the shim (verified to exist):
#   tests/sdd_scripts/test_check_task_state.py   (from scripts.sdd.check_task_state import find_violations, main :6)
#   tests/sdd_scripts/test_check_task_graph.py   (from scripts.sdd.check_task_graph import check_graph, main, … :6)
#   tests/sdd_scripts/test_worktree_status.py    (patch("scripts.sdd.worktree_status._git" / ".WORKTREE_ROOT" …) :120-122)
#   packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py
#       (import scripts.sdd as scripts_sdd_pkg :20; copies Path(scripts_sdd_pkg.__file__).parent / "close_task.sh" :33)
#   packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_workflow_contracts.py
#       (from scripts.sdd.finalize_task import TaskEvidenceStaleError, finalize_task :45)
```

### Does NOT Exist
- ~~`parrot.sdd.scripts.close_task`~~ — TASK-4087. Do not reference it from
  `finalize_task` here.
- ~~An `argv` parameter on `worktree_status.main`~~ — it is `def main() -> int:`. The
  shim calls `_impl.main()` with no arguments, and the test passes CLI args via
  `sys.argv` (subprocess).
- ~~`parrot.flows.dev_loop.test_scope` imported as a dotted `parrot.*` module by
  check_task_graph~~ — it is deliberately imported by path as the top-level name
  `test_scope`, which avoids the heavy `parrot.flows.dev_loop` package `__init__`. Keep
  the path import.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/check_task_state.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/check_task_graph.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py", "action": "CREATE"},
    {"path": "scripts/sdd/finalize_task.py", "action": "MODIFY"},
    {"path": "scripts/sdd/check_task_state.py", "action": "MODIFY"},
    {"path": "scripts/sdd/check_task_graph.py", "action": "MODIFY"},
    {"path": "scripts/sdd/worktree_status.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_scripts_task_state.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/finalize_task.py#main",
    "sym:scripts/sdd/finalize_task.py#_git_toplevel",
    "sym:scripts/sdd/finalize_task.py#_close_task_isolated",
    "sym:scripts/sdd/check_task_state.py#main",
    "sym:scripts/sdd/check_task_graph.py#main",
    "sym:scripts/sdd/check_task_graph.py#_load_contract",
    "sym:scripts/sdd/worktree_status.py#main",
    "sym:scripts/sdd/worktree_status.py#_git",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py#check_fidelity",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py#parse_task_files",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py#resolve_durable_root"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# The alias shim fixed by the FEAT-633 brief (also used by TASK-4085):
"""Compatibility shim — moved to ``parrot.sdd.scripts.<name>`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import <name> as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### Key Constraints
- **`git mv` first, then edit.** The only content changes are the ones in the blueprint.
- `raise SystemExit(_impl.main())` is equivalent to `worktree_status`'s original
  `sys.exit(main())`.
- `test_finalize_task.py` copies the real `scripts/sdd/close_task.sh` (still the original
  bash script in this task) into a temporary repo and runs `finalize_task` against it.
  The test keeps passing because `close_script` (line 394) is unchanged.
- **Worktree gotcha (same as TASK-4085).** Inside the FEAT-633 worktree, the shims only
  resolve with `PYTHONPATH=packages/ai-parrot/src`, because the editable install points
  at the main checkout, which has no `parrot.sdd` until merge.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/` — the kernel `check_task_graph` loads by path.
- TASK-4085 shims — identical pattern.

---

## Implementation Blueprint

### Steps (in order)
1. Run `git mv` once per file:
   `git mv scripts/sdd/{finalize_task,check_task_state,check_task_graph,worktree_status}.py packages/ai-parrot/src/parrot/sdd/scripts/`.
   *Why*: this keeps history.
2. Apply the `check_task_graph` and `worktree_status` edits below. *Why*: the package
   must not depend on the repository layout or on the repo-local `scripts` package.
3. Commit the renames on their own, then write the four shims. *Why*: rename detection
   stays at about 100%.
4. Write the test file and run every Validation Command. *Why*: the shim must keep the
   private-name monkeypatching in `test_worktree_status.py` and the close_task fixture in
   `test_finalize_task.py` working.

### `packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py` (CREATE)
```python
# git mv scripts/sdd/finalize_task.py packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py
# No line changes. Deliberately untouched: :394 close_script lookup, :598 prog string, :53-56 fcntl fallback.
```

### `packages/ai-parrot/src/parrot/sdd/scripts/check_task_state.py` (CREATE)
```python
# git mv scripts/sdd/check_task_state.py packages/ai-parrot/src/parrot/sdd/scripts/check_task_state.py
# No line changes.
```

### `packages/ai-parrot/src/parrot/sdd/scripts/check_task_graph.py` (CREATE)
```python
# git mv scripts/sdd/check_task_graph.py packages/ai-parrot/src/parrot/sdd/scripts/check_task_graph.py, then:
# occurrences: 1 (verified: grep -c '_KERNEL_DIR = Path(__file__).resolve().parents\[2\] / "packages/ai-parrot/src/parrot/flows/dev_loop"' scripts/sdd/check_task_graph.py)
# REPLACE — `_KERNEL_DIR = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"` (verified: scripts/sdd/check_task_graph.py:59)
# parrot/sdd/scripts/check_task_graph.py -> parents[2] is the `parrot` package dir (package-relative, wheel-safe).
_KERNEL_DIR = Path(__file__).resolve().parents[2] / "flows" / "dev_loop"
```

### `packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py` (CREATE)
```python
# git mv scripts/sdd/worktree_status.py packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py, then:
# occurrences: 1 (verified: grep -c 'from scripts.sdd.sdd_meta import (  # verified' scripts/sdd/worktree_status.py)
# REPLACE — lines 20-21 (verified: scripts/sdd/worktree_status.py:20-21):
#   `# scripts/sdd/sdd_meta.py is a re-export shim; the definition lives in the package.`
#   `from scripts.sdd.sdd_meta import (  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:322`
# parrot/sdd/scripts/sdd_meta.py (TASK-4085) re-exports parrot.knowledge.wiki.ledger.sdd_meta.
from parrot.sdd.scripts.sdd_meta import (  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:322
```

### `scripts/sdd/finalize_task.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""Finalize a verified task deterministically without committing or pushing.' scripts/sdd/finalize_task.py)
# REPLACE — whole file (original moved by git mv); first line was
#   `"""Finalize a verified task deterministically without committing or pushing.` (verified: scripts/sdd/finalize_task.py:1)
#   original entry: `def main(argv: list[str] | None = None) -> int:` (:596)
"""Compatibility shim — moved to ``parrot.sdd.scripts.finalize_task`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import finalize_task as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `scripts/sdd/check_task_state.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""``check_task_state.py`` — read-only backstop for stalled SDD task files.' scripts/sdd/check_task_state.py)
# REPLACE — whole file; first line was `"""``check_task_state.py`` — read-only backstop for stalled SDD task files.`
#   (verified: scripts/sdd/check_task_state.py:1); original entry `def main(argv: list[str] | None = None) -> int:` (:163)
"""Compatibility shim — moved to ``parrot.sdd.scripts.check_task_state`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import check_task_state as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `scripts/sdd/check_task_graph.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""``check_task_graph.py`` — deterministic lint for a per-spec task graph.' scripts/sdd/check_task_graph.py)
# REPLACE — whole file; first line was `"""``check_task_graph.py`` — deterministic lint for a per-spec task graph.`
#   (verified: scripts/sdd/check_task_graph.py:1); original entry `def main(argv: list[str] | None = None) -> int:` (:445)
"""Compatibility shim — moved to ``parrot.sdd.scripts.check_task_graph`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import check_task_graph as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `scripts/sdd/worktree_status.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""Discover SDD worktrees and report their task state and health.' scripts/sdd/worktree_status.py)
# REPLACE — whole file; first line was `"""Discover SDD worktrees and report their task state and health.`
#   (verified: scripts/sdd/worktree_status.py:1); original entry `def main() -> int:` (:614) — NO argv, so call it bare.
"""Compatibility shim — moved to ``parrot.sdd.scripts.worktree_status`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import worktree_status as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `packages/ai-parrot/tests/sdd/test_scripts_task_state.py` (CREATE)
See **Test Specification**. That block is the starting file.

### FILL IN checklist
- [ ] None in production code: every change is mechanical.
- [ ] Completion Note: record the `finalize_task.py:394` `scripts/sdd/close_task.sh`
  dependency as an open follow-up. A foreign repo lacks that file, and the fix needs
  `parrot.sdd.scripts.close_task` from TASK-4087. Also record the pre-existing heavy
  `parrot.flows.dev_loop` import (about 2.4 s, navconfig chdir) in `finalize_task`.

---

## Acceptance Criteria

- [ ] AC-1: `python -m parrot.sdd.scripts.<name> --help` exits 0 from a non-repo cwd
  for `finalize_task`, `check_task_state`, `check_task_graph` and `worktree_status`.
- [ ] AC-2: `scripts.sdd.<name> is parrot.sdd.scripts.<name>` for all four.
- [ ] AC-3: `parrot.sdd.scripts.check_task_graph._KERNEL_DIR` is
  `<parrot package dir>/flows/dev_loop`, exists, and contains `test_scope/contract.py`.
  `_load_contract()` succeeds.
- [ ] AC-4: The moved files differ from their originals only in the lines the blueprint
  lists (`git diff -M` shows renames).
- [ ] AC-5: The existing suites listed in Validation Commands pass unmodified.
- [ ] AC-6: `ruff check packages/ai-parrot/src/parrot/sdd/scripts scripts/sdd packages/ai-parrot/tests/sdd`
  is clean.
- [ ] Spec §5: "`scripts/sdd/` wrappers keep the monorepo's existing invocations working"
  (for these four).

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/sdd/test_scripts_task_state.py -q`
- `pytest tests/sdd_scripts/test_check_task_state.py -q`
- `pytest tests/sdd_scripts/test_check_task_graph.py -q`
- `pytest tests/sdd_scripts/test_worktree_status.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_workflow_contracts.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_scripts_task_state.py
"""FEAT-633 move B1: task-state helpers live in parrot.sdd.scripts; scripts/sdd shims alias them."""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC = REPO_ROOT / "packages" / "ai-parrot" / "src"
MOVED = ("finalize_task", "check_task_state", "check_task_graph", "worktree_status")


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(SRC), str(REPO_ROOT), env.get("PYTHONPATH", "")])
    return env


@pytest.mark.parametrize("name", MOVED)
def test_module_help_from_foreign_cwd(name: str, tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", f"parrot.sdd.scripts.{name}", "--help"],
        cwd=tmp_path, env=_env(), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("name", MOVED)
def test_shim_aliases_package_module(name: str) -> None:
    assert importlib.import_module(f"scripts.sdd.{name}") is importlib.import_module(f"parrot.sdd.scripts.{name}")


def test_check_task_graph_kernel_is_package_relative() -> None:
    import parrot
    from parrot.sdd.scripts import check_task_graph

    assert check_task_graph._KERNEL_DIR == Path(parrot.__file__).resolve().parent / "flows" / "dev_loop"
    assert (check_task_graph._KERNEL_DIR / "test_scope" / "contract.py").is_file()
    assert check_task_graph._load_contract() is not None


def test_worktree_status_main_takes_no_argv() -> None:
    import inspect

    from parrot.sdd.scripts import worktree_status

    assert list(inspect.signature(worktree_status.main).parameters) == []
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4086 parrot-installer verified`.
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
