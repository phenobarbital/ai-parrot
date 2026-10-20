# TASK-4508: SDD helpers move D: closeout and Validation Contract helpers into parrot.sdd.scripts

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4085
**Assigned-to**: unassigned

---

## Context

Added by the 2026-10-19 readiness review (dev `9f51c7735`). The shipped SDD markdown calls four
repo-local helpers that no move task covered, so after TASK-4089 rewrites the markdown to
`parrot sdd run <name>` they would not exist in a foreign repo. In that case
`test_no_repo_script_refs` fails, and so do the C3 scenarios in TASK-4091. The spec's C12 premise
("`review_checkpoint` is the only one") no longer holds. Two of the four landed on 2026-10-16,
before spec rev 0.3/0.4; the other two came with FEAT-699 and FEAT-703.

| Helper | Shipped callers on dev | Notes |
|---|---|---|
| `cache_test_contract` | `.claude/commands/sdd-task.md:369`, `.agents/skills/sdd-task/SKILL.md:110`, `.agent/workflows/sdd-task.md:365` | FEAT-699. Finds `test_scope` through a monorepo `_KERNEL_PARENT` (`:15`) |
| `test_report` | `.claude/commands/sdd-done.md:257,277`, `.agents/skills/sdd-done/SKILL.md:131,134`, `.agent/workflows/sdd-done.md:170,190` | FEAT-695. Monorepo `_KERNEL_PARENT` (`:18`) |
| `check_e2e_closeout` | `.claude/commands/sdd-done.md:206`, `.agents/skills/sdd-done/SKILL.md:100` | FEAT-703. Imports `yaml` (core dependency `PyYAML>=6.0.2`) and, lazily, `parrot.e2e` (ai-parrot-server), reporting MISSING when that is absent |
| `close_resolved_issues` | `.claude/commands/sdd-done.md:414` and both twins | Uses `pydantic` (core), the `wikitoolkit` CLI and `git` through `subprocess` |

This is the same mechanical move as TASK-4085–4088: `git mv` into `parrot.sdd.scripts`, then
rewrite the path loaders so they are package-relative and therefore safe inside a wheel. A shim
stays at each old path, so `python -m scripts.sdd.<name>` and `from scripts.sdd import <name>`
keep working in this repo. The shipped invocations are rewritten by TASK-4089, which depends on
this task. TASK-4070's helper map lists all four as "moved by TASK-4508".

`nightly_red_set` does **not** move. Only `.github/workflows/nightly-tests.yml:134` calls it (by
path), it uses only the stdlib, and nothing shipped references it.

---

## Readiness review — 2026-10-19 (dev 9f51c7735)
- Created by the readiness review; no prior version. Spec §2/M6's helper list and the C12 premise
  are stale. Spec rev 0.5 should list these four modules (see `sdd/state/FEAT-633/`).
- Resolved by spec rev 0.5 (2026-10-20): C18 confirms this move and the package-relative loaders.
  C21 settles how `cache_test_contract`/`test_report` behave in a foreign repo (`test_command`
  switch, TASK-4089/4299/4091). This task stays a mechanical move with no behaviour change.

---

## Scope

- `git mv scripts/sdd/<name>.py packages/ai-parrot/src/parrot/sdd/scripts/<name>.py` for the four
  helpers, keeping history.
- In the moved `cache_test_contract.py` and `test_report.py`, make `_KERNEL_PARENT`
  package-relative: `Path(__file__).resolve().parents[2] / "flows" / "dev_loop"`. Use exactly the
  rewrite TASK-4088 applies to `select_tests`: `parents[2]` is the `parrot` package directory.
- Update the `Usage:` lines in the moved modules' docstrings from `python -m scripts.sdd.<name>`
  to `python -m parrot.sdd.scripts.<name>`. No other line changes.
- Recreate each old path as an alias shim of exactly the form TASK-4085 uses for `id_ledger`.
- Add `packages/ai-parrot/tests/sdd/test_scripts_closeout_helpers.py`.

**NOT in scope**:
- Rewriting any `.md` invocation. TASK-4089 does that and adds these four names to its
  `MOVED`/`_MOVED`.
- `nightly_red_set.py` (stays repo-local, see Context).
- Changing helper behaviour, CLI flags, or the `test_scope` kernel itself.
- How FEAT-699's Validation Contract steps behave in a foreign repo (spec rev 0.5 open
  decision C7/FEAT-699; see the checkpoint in `sdd/state/FEAT-633/`).
- Registering the helpers anywhere. TASK-4091's `parrot sdd run` discovers helpers with
  `pkgutil.iter_modules` over `parrot.sdd.scripts`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/cache_test_contract.py` | CREATE | `git mv` + package-relative `_KERNEL_PARENT` (`:15`) + docstring path |
| `packages/ai-parrot/src/parrot/sdd/scripts/test_report.py` | CREATE | `git mv` + package-relative `_KERNEL_PARENT` (`:18`) + `Usage:` lines (`:4-5`) |
| `packages/ai-parrot/src/parrot/sdd/scripts/check_e2e_closeout.py` | CREATE | `git mv` (no line changes) |
| `packages/ai-parrot/src/parrot/sdd/scripts/close_resolved_issues.py` | CREATE | `git mv` (no line changes besides any `Usage:` path in its docstring) |
| `scripts/sdd/cache_test_contract.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/test_report.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/check_e2e_closeout.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/close_resolved_issues.py` | MODIFY | Becomes alias shim |
| `packages/ai-parrot/tests/sdd/test_scripts_closeout_helpers.py` | CREATE | Importability, `-m --help`, shim identity, package-relative kernel path |

---

## Codebase Contract (Anti-Hallucination)

> Verified on dev `9f51c7735` / `dac9766b7`.

### Verified Imports
```python
# packages/ai-parrot/src/parrot/sdd/scripts/__init__.py — created by TASK-4085 (dependency)
from parrot.sdd.scripts import cache_test_contract   # after this task
# test_scope kernel modules the two loaders import by path (already in core, ship with the wheel):
#   packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py   (cache_test_contract)
#   packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py     (test_report)
```

### Existing Signatures to Use
```python
# scripts/sdd/cache_test_contract.py (80 lines)
#   :1  """``cache_test_contract.py`` — cache a spec's §4 Validation Contract into its per-spec index (FEAT-699).
#   :15 _KERNEL_PARENT = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"
#   :18 def _load_contract() -> ModuleType:   # sys.path.insert(0, _KERNEL_PARENT); import test_scope.contract
#   :45 def main(argv: list[str] | None = None) -> int:
#   :79 if __name__ == "__main__":
# scripts/sdd/test_report.py (112 lines)
#   :1  #!/usr/bin/env python3
#   :2  """Render FEAT-695 test evidence for the ``/sdd-done`` closeout.
#   :4-5 Usage: python -m scripts.sdd.test_report decide-rerun|render ...
#   :18 _KERNEL_PARENT = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"
#   :21 def _load_report() -> ModuleType:     # sys.path.insert(0, _KERNEL_PARENT); import test_scope.report
#   :73 def main(argv: list[str] | None = None) -> int:
#   :111 if __name__ == "__main__":
# scripts/sdd/check_e2e_closeout.py (235 lines)
#   :1  #!/usr/bin/env python
#   :22 import yaml
#   :106-107 from parrot.e2e.errors import ...; from parrot.e2e.evidence import verify_evidence  (lazy, inside a function)
#   :201 def main(argv: Optional[Sequence[str]] = None) -> int:
#   :234 if __name__ == "__main__":
# scripts/sdd/close_resolved_issues.py (265 lines)
#   :1  """``close_resolved_issues.py`` — close the ledger issues a finished feature fixed.
#   :49 from pydantic import BaseModel, Field
#   :242 def main(argv: list[str] | None = None) -> int:
#   :264 if __name__ == "__main__":
# None of the four imports another scripts.sdd module; no other module in scripts/ or packages/ imports them.
```

Existing tests that must keep passing through the shims (unchanged):
- `tests/sdd_scripts/test_cache_test_contract.py` (`from scripts.sdd import cache_test_contract as cli`, `:8`)
- `tests/sdd_scripts/test_test_report.py` (`from scripts.sdd import test_report`, `:11`)
- `tests/sdd_scripts/test_check_e2e_closeout.py` (`from scripts.sdd.check_e2e_closeout import (...)`,
  `:17`; monkeypatches `builtins.__import__` to block `parrot.e2e` at `:101`/`:124`)
- `tests/sdd_scripts/test_close_resolved_issues.py` (`from scripts.sdd.close_resolved_issues import ...`, `:11`)

### Does NOT Exist
- ~~`parrot.sdd.scripts.cache_test_contract` / `.test_report` / `.check_e2e_closeout` / `.close_resolved_issues`~~ before this task.
- ~~A helper registry or allowlist for `parrot sdd run`~~: discovery is `pkgutil.iter_modules` (TASK-4091).
- ~~`parrot.e2e` in core~~: it ships in ai-parrot-server; keep the import lazy and the MISSING path intact.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/cache_test_contract.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/test_report.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/check_e2e_closeout.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/close_resolved_issues.py", "action": "CREATE"},
    {"path": "scripts/sdd/cache_test_contract.py", "action": "MODIFY"},
    {"path": "scripts/sdd/test_report.py", "action": "MODIFY"},
    {"path": "scripts/sdd/check_e2e_closeout.py", "action": "MODIFY"},
    {"path": "scripts/sdd/close_resolved_issues.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_scripts_closeout_helpers.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/cache_test_contract.py#main",
    "sym:scripts/sdd/cache_test_contract.py#_load_contract",
    "sym:scripts/sdd/test_report.py#main",
    "sym:scripts/sdd/test_report.py#_load_report",
    "sym:scripts/sdd/check_e2e_closeout.py#main",
    "sym:scripts/sdd/close_resolved_issues.py#main"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
TASK-4088's `select_tests` move (package-relative `_KERNEL_PARENT`) and TASK-4085's alias shim:

```python
"""Compatibility shim — moved to ``parrot.sdd.scripts.<name>`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import <name> as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### Key Constraints
- `git mv` first and edit second, so `git log --follow` keeps the history.
- `sys.modules[__name__] = _impl` makes `scripts.sdd.<name>` the *same* module object. Tests that
  monkeypatch module attributes therefore keep working.
- `check_e2e_closeout` must still degrade to MISSING when `parrot.e2e` cannot be imported. Keep its
  lazy import exactly where it is.
- `close_resolved_issues` resolves `wikitoolkit` from `PATH`. Do not hardcode a path.
- Never `import parrot` at module top level in the two `_KERNEL_PARENT` helpers beyond what they
  already do. Their loaders import `test_scope.*` by path on purpose.

### References in Codebase
- `sdd/tasks/active/TASK-4088-*.md`: the `select_tests` `_KERNEL_PARENT` REPLACE block.
- `sdd/tasks/active/TASK-4085-*.md`: the `scripts/sdd/id_ledger.py` shim block.

---

## Implementation Blueprint

### Steps (in order)
1. Confirm TASK-4085 is done (`packages/ai-parrot/src/parrot/sdd/scripts/__init__.py` exists).
2. `git mv` the four files into `packages/ai-parrot/src/parrot/sdd/scripts/`.
3. Apply the two `_KERNEL_PARENT` rewrites and the docstring `Usage:` path updates below.
4. Recreate the four old paths as shims.
5. Write the new test file; run the Validation Commands.

### `packages/ai-parrot/src/parrot/sdd/scripts/cache_test_contract.py` (CREATE via git mv)
```python
# occurrences: 1 (verified: grep -c '_KERNEL_PARENT = Path(__file__).resolve().parents\[2\] / "packages/ai-parrot/src/parrot/flows/dev_loop"' scripts/sdd/cache_test_contract.py)
# REPLACE — (verified: scripts/sdd/cache_test_contract.py:15)
# parrot/sdd/scripts/cache_test_contract.py -> parents[2] is the `parrot` package dir (package-relative, wheel-safe).
_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "flows" / "dev_loop"
```

### `packages/ai-parrot/src/parrot/sdd/scripts/test_report.py` (CREATE via git mv)
```python
# occurrences: 1 (verified: same grep against scripts/sdd/test_report.py)
# REPLACE — (verified: scripts/sdd/test_report.py:18)
_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "flows" / "dev_loop"
# and in the module docstring (:4-5): `python -m scripts.sdd.test_report` -> `python -m parrot.sdd.scripts.test_report`
```

### `scripts/sdd/<name>.py` × 4 (MODIFY — whole-file REPLACE with the shim)
Use the shim shown under Pattern to Follow, with `<name>` set to each of `cache_test_contract`,
`test_report`, `check_e2e_closeout` and `close_resolved_issues`.

### `packages/ai-parrot/tests/sdd/test_scripts_closeout_helpers.py` (CREATE)
```python
"""FEAT-633 move D: closeout/Validation Contract helpers live in parrot.sdd.scripts."""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

MOVED = ("cache_test_contract", "test_report", "check_e2e_closeout", "close_resolved_issues")


@pytest.mark.parametrize("name", MOVED)
def test_importable_from_package(name: str) -> None:
    """Each helper imports from parrot.sdd.scripts and exposes main()."""
    mod = importlib.import_module(f"parrot.sdd.scripts.{name}")
    assert callable(mod.main)


@pytest.mark.parametrize("name", MOVED)
def test_module_help_runs(name: str) -> None:
    """``python -m parrot.sdd.scripts.<name> --help`` exits 0."""
    proc = subprocess.run([sys.executable, "-m", f"parrot.sdd.scripts.{name}", "--help"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("name", MOVED)
def test_shim_is_same_module(name: str) -> None:
    """The scripts.sdd shim aliases the package module object (FILL IN: skip when the repo root is not importable)."""
    ...


@pytest.mark.parametrize("name", ("cache_test_contract", "test_report"))
def test_kernel_parent_is_package_relative(name: str) -> None:
    """_KERNEL_PARENT points inside the installed parrot package, not at a monorepo path."""
    mod = importlib.import_module(f"parrot.sdd.scripts.{name}")
    import parrot

    assert Path(mod._KERNEL_PARENT) == Path(parrot.__file__).resolve().parent / "flows" / "dev_loop"
    assert (Path(mod._KERNEL_PARENT) / "test_scope").is_dir()
```

### FILL IN checklist
- [ ] `test_shim_is_same_module`: `importlib.import_module(f"scripts.sdd.{name}") is importlib.import_module(f"parrot.sdd.scripts.{name}")`.
- [ ] Check whether `close_resolved_issues`'s docstring carries a `python -m scripts.sdd…` usage line; update it the same way.

---

## Acceptance Criteria

- [ ] The four modules exist under `packages/ai-parrot/src/parrot/sdd/scripts/` with history kept (`git log --follow`).
- [ ] `grep -rn 'packages/ai-parrot/src' packages/ai-parrot/src/parrot/sdd/scripts/{cache_test_contract,test_report}.py` finds nothing.
- [ ] `python -m parrot.sdd.scripts.<name> --help` exits 0 for all four.
- [ ] The four old paths are shims; `python -m scripts.sdd.<name> --help` still exits 0.
- [ ] The existing suites listed under Validation Commands pass unchanged.
- [ ] `ruff check` passes on every touched Python file.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_scripts_closeout_helpers.py -q`
- `pytest tests/sdd_scripts/test_cache_test_contract.py tests/sdd_scripts/test_test_report.py tests/sdd_scripts/test_check_e2e_closeout.py tests/sdd_scripts/test_close_resolved_issues.py -q`
- `pytest tests/sdd_scripts/test_e2e_closeout_contract.py tests/sdd/test_ledger_workflow_twins.py -q` (these pin the *markdown* strings; they stay green here because TASK-4089, not this task, rewrites the markdown)

---

## Test Specification

See the blueprint test module: importability, `-m --help`, shim identity, and a
package-relative `_KERNEL_PARENT` that resolves inside the installed `parrot` package.

---

## Agent Instructions

1. Verify TASK-4085 is done, then re-check every Existing Signature line number before editing.
2. Do not touch any `.md` file, `nightly_red_set.py`, or the `test_scope` kernel.
3. If a moved helper turns out to import another `scripts.sdd` module (none does on `9f51c7735`),
   STOP and record it in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
