# TASK-5175: `parrot sdd worktree root` CLI and `conf.py` derivation

**Feature**: FEAT-802 — Worktree Root Under `.parrot/`
**Spec**: `sdd/specs/worktree-root-under-parrot.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5174
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (second half). Shell workflows (`/sdd-done`, `/sdd-next`, `/remove-worktree`, the
agent twins — TASK-5180..5182) must obtain the effective root from the same resolver as Python, so a
read-only `parrot sdd worktree root --root PATH` verb is added. `parrot.conf` stops defining its own
default and derives `WORKTREE_BASE_PATH` / `DEV_LOOP_REPO_BASE_PATH` from `worktree_root()`, so the
dev-loop moves with every other consumer (G1, G3).

---

## Scope

- Create `parrot/sdd/scripts/worktree_root.py` with `main(argv=None) -> int`: required `--root PATH`,
  prints `worktree_root(Path(args.root))` plus newline, exit 0; argparse usage errors exit 2.
- Mount it: `VERBS["worktree"]["root"] = ("worktree_root", (), "Print the resolved worktree root.")`.
- Rewrite `conf.py:933-939` and `:975-985` to derive both settings through `worktree_root()`; update the two comments.
- Update `packages/ai-parrot/tests/test_conf.py::test_worktree_base_path_default` and add the
  `DEV_LOOP_REPO_BASE_PATH` assertion; add `test_worktree_root_cli` / `test_conf_worktree_base_path_derives` to `test_config.py`.

**NOT in scope**: shell consumers of the verb (TASK-5180..5182); any `parrot/flows/` change (they keep
reading `conf.WORKTREE_BASE_PATH`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_root.py` | CREATE | read-only root printer |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | mount `worktree root` |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | derive `WORKTREE_BASE_PATH` / `DEV_LOOP_REPO_BASE_PATH` |
| `packages/ai-parrot/tests/sdd/test_config.py` | MODIFY | CLI + conf derivation tests |
| `packages/ai-parrot/tests/test_conf.py` | MODIFY | new default suffix |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.sdd.config import worktree_root   # created by TASK-5174 in parrot/sdd/config.py
from navconfig import BASE_DIR, config        # verified: parrot/conf.py:6
import os                                     # verified: parrot/conf.py:2
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/cli.py
VERBS: dict[str, dict[str, tuple[str, tuple[str, ...], str]]] = {     # line 237
    "worktree": {                                                       # line 238
        "ensure": ("ensure_worktree", (), "Create or reuse the feature/hotfix worktree (idempotent)."),  # line 239
def mounted_modules() -> set[str]:                                      # line 311
def _mount(noun, verb, module, prefix, help_) -> None:                  # line 316 — calls parrot.sdd.scripts.<module>.main([*prefix, *args])

# packages/ai-parrot/src/parrot/conf.py
_wt: str = config.get("WORKTREE_BASE_PATH", fallback=str(BASE_DIR / ".claude/worktrees"))   # line 938
WORKTREE_BASE_PATH: str = os.path.normpath(_wt) if os.path.isabs(_wt) else os.path.normpath(str(BASE_DIR / _wt))  # line 939
_repos: str = config.get(                                                # line 979
    "DEV_LOOP_REPO_BASE_PATH",
    fallback=str(BASE_DIR / ".claude/worktrees/repos"),                 # line 981
)
DEV_LOOP_REPO_BASE_PATH: str = (                                         # lines 983-985
    os.path.normpath(_repos) if os.path.isabs(_repos) else os.path.normpath(str(BASE_DIR / _repos))
)

# packages/ai-parrot/tests/test_conf.py
def test_worktree_base_path_default(self):                              # line 25 — asserts endswith(".claude/worktrees")
```

### Does NOT Exist
- ~~`parrot.conf.WORKTREE_ROOT`~~ — conf only exposes `WORKTREE_BASE_PATH`.
- ~~`parrot.sdd.scripts.worktree_root`~~ before this task — you create it.
- The root script must NOT import `parrot.conf` or `navconfig` (wheel-only foreign repos have no navconfig settings) and must not `mkdir` or `chdir`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_root.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/conf.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_config.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_conf.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#VERBS",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#mounted_modules"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `parrot/sdd/__init__.py` is import-free and `parrot/sdd/config.py` imports only pydantic, so
  `from parrot.sdd.config import worktree_root` inside `conf.py` creates no cycle (spec §7).
- `conf.py` keeps the FEAT-253 G1 rule: navconfig value (env AND `.env` files) wins; relative joins
  `BASE_DIR`; absolute verbatim. `worktree_root(BASE_DIR, override=<navconfig value or None>)`
  implements exactly that, because an override beats `os.environ`.
- `DEV_LOOP_REPO_BASE_PATH` default becomes `f"{WORKTREE_BASE_PATH}/repos"`; an explicit value keeps the relative→join / absolute→verbatim rule.

---

## Implementation Blueprint

### Steps (in order)
1. Create the root script — *why*: shell twins need the exact Python resolution without navconfig.
2. Mount it under `worktree` — *why*: `parrot sdd worktree root` is the documented interface (spec §2).
3. Rewrite the two `conf.py` blocks — *why*: AC3, the dev-loop must follow the resolver.
4. Update `test_conf.py` and add the two tests in `test_config.py`; run validation.

### `packages/ai-parrot/src/parrot/sdd/scripts/worktree_root.py` (CREATE)
```python
"""Print the resolved SDD worktree root for a primary checkout (FEAT-802).

Read-only: never creates directories, never changes the working directory, never loads
``parrot.conf``. Shell workflows capture its stdout:
``WORKTREES_DIR=$(parrot sdd worktree root --root "$MAIN_ROOT") || exit $?``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from parrot.sdd.config import worktree_root


def main(argv: Sequence[str] | None = None) -> int:
    """Print ``worktree_root(--root)`` and exit 0; argparse usage errors exit 2."""
    parser = argparse.ArgumentParser(prog="parrot sdd worktree root", description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, type=Path, help="The primary checkout of the repository.")
    args = parser.parse_args(argv)
    sys.stdout.write(f"{worktree_root(args.root)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why this shape**: spec §3 M1 fixes `--root`, stdout and exit codes; `sys.stdout.write` keeps the
output to exactly one line (no logging config is loaded in a wheel-only install).

### `packages/ai-parrot/src/parrot/sdd/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"ensure": ("ensure_worktree", (), "Create or reuse the feature/hotfix worktree (idempotent)."),' packages/ai-parrot/src/parrot/sdd/cli.py)
# AFTER — insert below that line (verified: cli.py:239)
        "root": ("worktree_root", (), "Print the resolved worktree root."),
```

### `packages/ai-parrot/src/parrot/conf.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_wt: str = config.get("WORKTREE_BASE_PATH", fallback=str(BASE_DIR / ".claude/worktrees"))' packages/ai-parrot/src/parrot/conf.py)
# REPLACE lines 933-939 (comment "# Absolute path under which feature worktrees are created." through the WORKTREE_BASE_PATH line) with:
# Absolute path under which feature worktrees are created (FEAT-802: one resolver,
# parrot.sdd.config.worktree_root). Default BASE_DIR/.parrot/worktrees; a relative
# WORKTREE_BASE_PATH joins BASE_DIR, an absolute one is honored verbatim (FEAT-253 G1).
from parrot.sdd.config import worktree_root as _worktree_root  # noqa: E402 — pydantic-only module, no cycle

WORKTREE_BASE_PATH: str = str(_worktree_root(BASE_DIR, override=config.get("WORKTREE_BASE_PATH", fallback=None)))
```
```python
# occurrences: 1 (verified: grep -c '    fallback=str(BASE_DIR / ".claude/worktrees/repos"),' packages/ai-parrot/src/parrot/conf.py)
# REPLACE lines 975-985 (comment "# Absolute path for dev-loop clones (FEAT-253 G1)." through the closing ")") with:
# Absolute path for dev-loop clones (FEAT-253 G1). Defaults to <WORKTREE_BASE_PATH>/repos so the
# dispatcher's cwd-safety guard (_enforce_cwd_under_worktree_base) passes.
# Same relative→join / absolute→verbatim rule as WORKTREE_BASE_PATH.
_repos: str = config.get("DEV_LOOP_REPO_BASE_PATH", fallback=f"{WORKTREE_BASE_PATH}/repos")
DEV_LOOP_REPO_BASE_PATH: str = (
    os.path.normpath(_repos) if os.path.isabs(_repos) else os.path.normpath(str(BASE_DIR / _repos))
)
```
**Why**: AC3. Keep `_repos` handling verbatim apart from the fallback so explicit settings behave as today.

### `packages/ai-parrot/tests/test_conf.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'assert conf.WORKTREE_BASE_PATH.endswith(os.path.join(".claude", "worktrees"))' packages/ai-parrot/tests/test_conf.py)
# REPLACE that line with:
        assert conf.WORKTREE_BASE_PATH.endswith(os.path.join(".parrot", "worktrees"))
        if conf.config.get("DEV_LOOP_REPO_BASE_PATH", fallback=None) is None:
            assert conf.DEV_LOOP_REPO_BASE_PATH == os.path.join(conf.WORKTREE_BASE_PATH, "repos")
```

### FILL IN checklist
- [ ] `test_config.py::test_worktree_root_cli` — default/relative/absolute override incl. a path with spaces; stdout == `f"{worktree_root(root)}\n"`; no directory created; missing `--root` → exit 2.
- [ ] `test_config.py::test_conf_worktree_base_path_derives` — skip when navconfig overrides `WORKTREE_BASE_PATH`; else equals `str(worktree_root(BASE_DIR))`.

---

## Acceptance Criteria

- [ ] Spec AC3: `conf.WORKTREE_BASE_PATH == str(worktree_root(BASE_DIR, override=<navconfig value>))`; unset → ends with `.parrot/worktrees`; `DEV_LOOP_REPO_BASE_PATH` defaults to `<WORKTREE_BASE_PATH>/repos`.
- [ ] Spec AC13: `parrot sdd worktree root --root PATH` prints exactly the resolver's absolute root, honours `WORKTREE_BASE_PATH`, writes nothing, does not import `parrot.conf`.
- [ ] `"worktree_root" in mounted_modules()`.
- [ ] `ruff check` clean on the three source files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_config.py -q`
- `pytest packages/ai-parrot/tests/test_conf.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_config.py — append
from parrot.sdd.scripts import worktree_root as worktree_root_script


@pytest.mark.parametrize("env", [None, "wt dir/x", "/abs/with space/wt"])
def test_worktree_root_cli(tmp_path, monkeypatch, capsys, env): ...
    # delenv first; set env when given; main(["--root", str(tmp_path)]) == 0;
    # capsys.readouterr().out == f"{worktree_root(tmp_path)}\n"; not (tmp_path / ".parrot").exists()
    # assert "parrot.conf" not in the modules imported by a fresh `python -c` run of the module (subprocess)


def test_conf_worktree_base_path_derives(): ...
```

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug worktree-root-under-parrot --feature-id FEAT-802`).
2. TASK-5174 must be `done` in `sdd/tasks/index/worktree-root-under-parrot.json`.
3. Verify the contract, mark `in-progress`, implement the blueprint, run the Validation Commands with `PYTHONPATH=<abs worktree>/packages/ai-parrot/src`.
4. Commit only the listed files; `parrot sdd task close TASK-5175 worktree-root-under-parrot verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
