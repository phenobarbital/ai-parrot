# TASK-5689: Resolve the effective directory before matching procedure guards

**Feature**: FEAT-899 — Procedure guards and plane — FEAT-891 review follow-ups
**Spec**: `sdd/specs/fixgroup-848b9a0ceee1.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:bab5aa4a8d70`

---

## Context

Spec §2 M1 / §3 Module 1 (review note 1 of `issue:bab5aa4a8d70`). `match_guards` tests `path_globs`
against the raw argument, so the mandatory `task-close` bypass guard (`mv` / `git mv` on
`sdd/tasks/active/*`) is evaded by `cd sdd/tasks/active && mv T.md ../completed/`, by
`git -C sdd/tasks/active mv T.md ../completed/` (the `-C` pair also breaks the `argv_prefix` test) and
by an absolute path. The guard must match the path the segment really acts on.

---

## Scope

- Add keyword arguments `checkout` and `cwd` to `match_guards` and track an effective directory
  (checkout-relative) across command segments.
- Treat a plain `cd <dir>` segment as a directory change for the segments after it.
- Strip leading git global `-C <dir>` options before the `argv_prefix` test; the directory applies to
  that segment only.
- Normalise each argument against the segment's effective directory and the checkout before the glob test.
- Pass `checkout` and `cwd` from `evaluate_command`.
- Tests: `test_match_guards_resolves_effective_directory`, `test_match_guards_default_arguments_unchanged`,
  `test_evaluate_command_denies_cd_bypass`.

**NOT in scope**: message truncation and probe semantics (TASK-5690); subshells, `pushd`/`popd`, shell
expansion (`~`, `$VAR`); other git global options (`-c`, `--git-dir`); the manifest and the index schema.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` | MODIFY | effective-directory tracking and path normalisation in `match_guards` |
| `packages/ai-parrot/tests/sdd/test_procedure_advice.py` | MODIFY | three new tests |

---

## Codebase Contract (Anti-Hallucination)

Verified against `909ec8aced` (dev after PR #2132, which rewrote the segment splitter and removed the
`break` after the first matching segment — every matching segment is now appended).

### Verified Imports
```python
# packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py — already imported at the top of the file
import fnmatch   # line 8
import os        # line 11
from pathlib import Path                               # line 14
from typing import Any, Callable, Literal, Mapping     # line 15

# packages/ai-parrot/tests/sdd/test_procedure_advice.py
from parrot.sdd.scripts import procedure_advice as advice   # line 15
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py  (stdlib only, never raises)
def checkout_root(cwd: Path) -> Path | None:                                  # line 39 — returns a RESOLVED path
def command_segments(command: str) -> list[list[str]]:                        # line 204
def _assignment(token: str) -> bool:                                          # line 227
def _clean(tokens: list[str]) -> tuple[str, list[str]]:                       # line 240 — ("", []) for a `cd` segment
def _normalise_path(value: str) -> str:                                       # line 283
def match_guards(index: Mapping[str, Any], command: str) -> list[dict[str, Any]]:   # line 291
def evaluate_command(command: str, cwd: Path, *, env: Mapping[str, str] | None = None) -> Advice:   # line 617
#   inside evaluate_command: `checkout = checkout_root(cwd)` and `matches = match_guards(index, command)` (line 631)

# packages/ai-parrot/tests/sdd/test_procedure_advice.py
GUARDS: list[dict]                                                            # line 17 — entry `parrot sdd task close` + bypass `git mv` on sdd/tasks/active/*
def _repo(tmp_path: Path, *, status: str = "in-progress", config: dict | None = None) -> Path:   # line 116 — plain checkout, branch feat-FEAT-1-demo, fresh plane
```

### Does NOT Exist
- ~~`match_guards(..., checkout=..., cwd=...)` today~~ — added by this task.
- ~~a bypass guard for plain `mv` in the test `GUARDS` / `_repo` index~~ — only the `git mv` bypass guard
  exists there; build a local guard list in the test when a plain `mv` guard is needed.
- ~~`parrot.*` imports in `procedure_advice.py`~~ — forbidden (the hook loads it as a script sibling).
- ~~`Path.is_relative_to` use~~ — not needed; keep the comparison textual so no filesystem access is added.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_procedure_advice.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py#match_guards",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py#_normalise_path",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py#_clean",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py#command_segments",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py#evaluate_command"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Standard library only; no helper may raise out of `match_guards` (its `try/except` stays).
- A command with no `cd` segment and no `git -C` option, called without the keyword arguments, must
  match exactly as before (spec AC2).
- A path that resolves outside the checkout must not become a checkout-relative match: keep its leading
  `..` or its absolute form.
- `matched["argv"]` stays the arguments after `argv_prefix` (for git: after the `-C` pairs were removed),
  because `_scope_for_guard` reads scope values from it.

### References in Codebase
- `packages/ai-parrot/src/parrot/sdd/_assets/sdd/procedures/sdd-workflow.yaml` — the `task-close` bypass guards this protects.

---

## Implementation Blueprint

### Steps (in order)
1. Replace `_normalise_path` with the keyword-argument version — *why*: every argument must be resolved
   against the segment's directory and the checkout before the glob test.
2. Add the four private helpers below `_normalise_path` — *why*: they keep `match_guards` readable and are
   the names fixed by spec §3 Module 1.
3. Rewrite the segment loop of `match_guards` to iterate `_located_segments(...)` — *why*: the directory
   is a property of the segment, computed once, not per guard.
4. Pass `checkout` and `cwd` from `evaluate_command` — *why*: the hook path is the one that must deny.
5. Add the three tests, run the Validation Commands, `ruff check --fix` both files.

### `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` (MODIFY) — block 1
```python
# occurrences: 1 (verified: grep -c 'def _normalise_path(value: str) -> str:' packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py)
# REPLACE the whole function starting at `def _normalise_path(value: str) -> str:` (verified: procedure_advice.py:283)
def _normalise_path(value: str, *, base: str = "", checkout: Path | None = None) -> str:
    """Normalize a guard argument to a POSIX-style checkout-relative path.

    A relative ``value`` is joined to ``base``; an absolute ``value`` inside ``checkout`` is made relative.
    """
    text = value.replace("\\", "/")
    if os.path.isabs(text):
        # FILL IN: when `checkout` is given and the normalised text is inside it, drop the checkout
        #   prefix (the checkout itself becomes "."); otherwise keep the absolute form — bounded by
        #   "a path outside the checkout matches no repository glob"
        pass
    elif base:
        text = f"{base}/{text}"
    normalized = os.path.normpath(text).replace(os.sep, "/").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _relative_directory(base: str, target: str, checkout: Path | None) -> str:
    """Return ``target`` as a checkout-relative POSIX directory, joined to ``base`` when relative."""
    directory = _normalise_path(target, base=base, checkout=checkout)
    return "" if directory == "." else directory


def _change_directory(tokens: list[str]) -> str | None:
    """Return the target of a plain ``cd <dir>`` segment, or None for any other segment."""
    # FILL IN: skip leading assignments (`_assignment`), require the executable basename `cd`, drop
    #   option tokens (start with "-", except a lone "-"), return the single remaining argument when it
    #   is not "-", else None — bounded by "exactly one non-option argument" (spec §2 M1)


def _git_directory(argv: list[str]) -> tuple[list[str], str | None]:
    """Strip leading git global ``-C <dir>`` options; return (remaining argv, last directory or None)."""
    # FILL IN: consume `-C <dir>` pairs from the front; a later relative <dir> is relative to the
    #   earlier one (git semantics) — bounded by "only -C is handled" (NOT in scope: -c, --git-dir)


def _located_segments(command: str, checkout: Path | None, cwd: Path | None) -> list[tuple[str, list[str], str]]:
    """Return ``(executable, argv, effective directory)`` for every non-``cd`` segment, in order."""
    # FILL IN: start `base` as `cwd` relative to `checkout` ("" when either is None or cwd is outside);
    #   for each `command_segments(command)` entry: a `_change_directory` hit updates `base` through
    #   `_relative_directory` and yields nothing; otherwise `_clean(tokens)`, and for executable "git"
    #   apply `_git_directory` and use its directory for that segment only
```
**Why this shape**: the helper names and `_normalise_path`/`match_guards` signatures are fixed by spec §3
Module 1. The comparison is textual (`checkout_root` already returns a resolved path) so the hook does
no extra filesystem work.

### `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` (MODIFY) — block 2
```python
# occurrences: 1 (verified: grep -c 'def match_guards(index: Mapping\[str, Any\], command: str) -> list\[dict\[str, Any\]\]:' …/procedure_advice.py)
# REPLACE the signature line `def match_guards(index: Mapping[str, Any], command: str) -> list[dict[str, Any]]:` (verified: procedure_advice.py:291)
def match_guards(
    index: Mapping[str, Any],
    command: str,
    *,
    checkout: Path | None = None,
    cwd: Path | None = None,
) -> list[dict[str, Any]]:
    """Return index guards matching any command segment, preserving index order."""

# inside the function:
#   `segments = command_segments(command)`  →  `segments = _located_segments(command, checkout, cwd)`
#   `for tokens in segments:` + `actual_executable, argv = _clean(tokens)`  →  `for actual_executable, argv, directory in segments:`
#   `_normalise_path(argument)`  →  `_normalise_path(argument, base=directory, checkout=checkout)`
```
**Why**: the guard validation, the `argv_prefix` test and the `matched["argv"]` contract stay as they are.

### `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` (MODIFY) — block 3
```python
# occurrences: 1 (verified: grep -c 'matches = match_guards(index, command)' …/procedure_advice.py)
# REPLACE `        matches = match_guards(index, command)` (verified: procedure_advice.py:631)
        matches = match_guards(index, command, checkout=checkout, cwd=Path(cwd))
```
**Why**: `checkout` is already computed two lines above (`checkout = checkout_root(cwd)`) and is not None here.

### `packages/ai-parrot/tests/sdd/test_procedure_advice.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_shared_root_plain_and_worktree(tmp_path: Path) -> None:' …/test_procedure_advice.py)
# BEFORE — insert above `def test_shared_root_plain_and_worktree(tmp_path: Path) -> None:` (verified: test_procedure_advice.py:77)
def test_match_guards_resolves_effective_directory(tmp_path: Path) -> None:
    """``cd``, ``git -C`` and absolute paths cannot hide the path a bypass guard protects."""
    # FILL IN: assert a match for the three evasions and no match for `cd docs && git mv a b` and for a
    #   path outside the checkout — bounded by spec §4 row 1


def test_match_guards_default_arguments_unchanged() -> None:
    """Without ``checkout``/``cwd`` a command with no ``cd`` and no ``git -C`` matches as before."""
    # FILL IN: repeat the assertions of test_match_guards_every_segment — bounded by AC2


def test_evaluate_command_denies_cd_bypass(tmp_path: Path) -> None:
    """The hook entry point denies a hand move hidden behind ``cd`` or ``git -C``."""
    # FILL IN: use `_repo(tmp_path)` and `advice.evaluate_command(..., root, env={})` — bounded by spec §4 row 3
```

### FILL IN checklist
- [ ] `_normalise_path` — absolute-path branch; bounded by "outside the checkout matches no glob"
- [ ] `_change_directory` — plain `cd <dir>` detection; bounded by "exactly one non-option argument"
- [ ] `_git_directory` — `-C` pairs only
- [ ] `_located_segments` — initial directory and per-segment directory
- [ ] three test bodies

---

## Acceptance Criteria

- [ ] `cd sdd/tasks/active && git mv T.md ../completed/`, `git -C sdd/tasks/active mv T.md ../completed/` and
      `git mv <checkout>/sdd/tasks/active/T.md <checkout>/sdd/tasks/completed/` match the bypass guard.
- [ ] `cd docs && git mv a b` and a path outside the checkout do not match.
- [ ] Every pre-existing test in `test_procedure_advice.py` and `test_procedure_guards.py` still passes.
- [ ] `test_advice_stdlib_only` passes.
- [ ] `ruff check` is clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_procedure_advice.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_procedure_guards.py -q`

---

## Test Specification

See the three test stubs in the blueprint; spec §4 rows 1–3 state what each asserts.

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug fixgroup-848b9a0ceee1 --feature-id FEAT-899`).
2. Verify the Codebase Contract, mark the task `in-progress` in `sdd/tasks/index/fixgroup-848b9a0ceee1.json`.
3. Implement from the blueprint, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the two files listed, close with the close script, fill in the Completion Note.

---

## Completion Note

**Completed by**: Claude Code (`/sdd-fix` session, actor `agent:sdd-fix:cb69fd31`)
**Date**: 2026-11-15
**Notes**: `match_guards` now takes `checkout`/`cwd` and resolves each argument against the segment's
effective directory: plain `cd <dir>` segments are followed, leading `git -C <dir>` options are stripped
before the `argv_prefix` test and applied to that segment, and absolute paths inside the checkout become
checkout-relative. `evaluate_command` passes both arguments. Code commit `ca79abefec`. Validation:
`pytest packages/ai-parrot/tests/sdd/test_procedure_advice.py packages/ai-parrot/tests/sdd/test_procedure_guards.py`
→ 45 passed; `ruff check` and `black --check` clean on both files.

**Deviations from spec**: none. Two details beyond the blueprint: a private `_located_segments` helper
holds the per-segment walk, and `match_guards` also catches `RuntimeError` (a symlink loop in
`Path.resolve()` on Python < 3.13) so it keeps its never-raises contract.
