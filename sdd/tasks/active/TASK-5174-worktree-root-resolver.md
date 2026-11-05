# TASK-5174: Worktree root resolver, legacy detection and migration recipe

**Feature**: FEAT-802 — Worktree Root Under `.parrot/`
**Spec**: `sdd/specs/worktree-root-under-parrot.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview and §3 Module 1. Today the worktree location is spelled in three unrelated
constants plus inline strings. This task creates the single resolver family in
`parrot/sdd/config.py` that every later task consumes: the root setting, the absolute root, the
detection of worktrees still registered under the legacy `.claude/worktrees/`, and the guarded
migration recipe printed by the installer and doctor (TASK-5179). It is the root of the task graph.

---

## Scope

- Add `DEFAULT_WORKTREE_ROOT`, `LEGACY_WORKTREE_ROOT`, `WORKTREE_ROOT_ENV` and
  `LegacyWorktreesError(RuntimeError)` to `parrot/sdd/config.py`.
- Implement `worktree_root_setting(override=None) -> str` and `worktree_root(repo_root, override=None) -> Path`.
- Implement `legacy_worktrees(repo_root) -> list[Path]` over `git worktree list --porcelain` (never raises).
- Implement `legacy_migration_recipe(repo_root, paths) -> list[str]`: hierarchy-preserving mapping,
  collision preflight at generation (raise `ValueError`) AND inside the emitted recipe, topmost moves
  only, one `git -C <repo> worktree repair <all new paths>` line, every path `shlex.quote`d.
- Write the M1 unit tests plus the executed-recipe integration test in `packages/ai-parrot/tests/sdd/test_config.py`.

**NOT in scope**: the `parrot sdd worktree root` CLI and `conf.py` (TASK-5175); any consumer of the
resolver (TASK-5176..5179); installer/doctor refusal (TASK-5179).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/config.py` | MODIFY | resolver constants, error class, four functions |
| `packages/ai-parrot/tests/sdd/test_config.py` | MODIFY | M1 resolver, legacy detection, recipe shape/collision/execution tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.sdd.config import SddConfig, SddConfigError, default_sdd_config, find_repo_root, load_sdd_config  # verified: packages/ai-parrot/tests/sdd/test_config.py:11-19
import json                                   # verified: parrot/sdd/config.py:5
from pathlib import Path                      # verified: parrot/sdd/config.py:6
from typing import Literal                    # verified: parrot/sdd/config.py:7
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator  # verified: parrot/sdd/config.py:9
```
`os`, `shlex`, `subprocess` and `collections.abc.Sequence` are stdlib and are NOT yet imported by `config.py` — add them.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/config.py
CONFIG_PATH = Path("sdd/config.json")                                   # line 11
class SddConfigError(ValueError): ...                                   # line 15
class SddConfig(BaseModel): ...                                         # line 19
def default_sdd_config() -> SddConfig:                                  # line 88
def find_repo_root(start: Path | None = None) -> Path | None:           # line 93 — walks up to first .git (dir or file)
def load_sdd_config(root: Path | None = None) -> SddConfig:             # line 106

# packages/ai-parrot/tests/sdd/test_config.py
def _repo(tmp_path: Path, config: dict | str | None = None) -> Path:   # line 23 — makes tmp_path/.git dir (NOT a real repo)
```

### Does NOT Exist
- ~~`parrot.sdd.paths`~~, ~~`parrot.sdd.worktree_root`~~ (module) — the resolver lives in `parrot/sdd/config.py`.
- ~~`parrot.sdd.config.WORKTREE_ROOT`~~ — the setting is a function, `worktree_root_setting()`.
- ~~`parrot sdd worktree migrate`~~ / any code that RUNS the recipe — parrot only prints it.
- ~~`git worktree move`~~ in the recipe — the recipe uses `mv` + explicit `git worktree repair`.
- `parrot/sdd/__init__.py` exports nothing and must stay import-free.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/config.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_config.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/config.py#find_repo_root",
    "sym:packages/ai-parrot/src/parrot/sdd/config.py#SddConfigError"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `parrot/sdd/config.py` must keep pydantic as its only third-party import — `parrot.conf`
  (TASK-5175) and the wheel-only `python -m parrot.sdd.scripts.*` entry points import it.
- `worktree_root_setting()` reads `os.environ` only (never navconfig). Blank (whitespace-only) values count as unset.
- `legacy_worktrees()` compares RESOLVED paths: `Path(entry).resolve()` must be relative to
  `(repo_root / LEGACY_WORKTREE_ROOT).resolve()`. Never raises: missing git binary, non-zero exit,
  non-repo → `[]`. Use `subprocess.run([...], capture_output=True, text=True, check=False)` inside
  `try/except OSError`.
- Recipe rules (spec §3 M1 docstring, §7 gotchas) are binding: preserve `<feature>--pool/<suffix>`
  hierarchy; overlapping old/new root → `ValueError`; duplicate destinations → `ValueError`;
  occupied destination (`os.path.lexists`, so dangling symlinks count) → `ValueError`; the emitted
  recipe re-checks every destination with `[ ! -e X ] && [ ! -L X ]` before ANY `mv`; parents are
  created with `mkdir -p`; only topmost registered ancestors are moved; the single repair line lists
  every mapped registration (descendants included). An empty `paths` returns `[]`.
- Every resolver test calls `monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)` first.

### References in Codebase
- `parrot/sdd/scripts/worktree_status.py::_parse_porcelain` (line 253) — porcelain parsing shape to mirror (do not import it: config.py must not import scripts).

---

## Implementation Blueprint

### Steps (in order)
1. Add the stdlib imports and the three constants + `LegacyWorktreesError` below `find_repo_root` — *why*: spec §2 fixes the names and their home module.
2. Implement `worktree_root_setting` / `worktree_root` — *why*: every consumer needs one rule for relative (repo-relative) vs absolute values.
3. Implement `legacy_worktrees` with porcelain parsing — *why*: the hard cut (TASK-5179) and the legacy status row (TASK-5177) need the registered list, not a directory scan.
4. Implement `legacy_migration_recipe` with generation-time preflight, then the emitted fail-fast subshell — *why*: a bare `mv` leaves prunable registrations and a collision must never nest or overwrite (spec §7).
5. Write the tests listed in the Test Specification; run the validation command.

### `packages/ai-parrot/src/parrot/sdd/config.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from typing import Literal' packages/ai-parrot/src/parrot/sdd/config.py)
# AFTER — replace the import block at lines 5-7 with:
import json
import os
import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Literal
```
```python
# occurrences: 1 (verified: grep -c 'def load_sdd_config(root: Path | None = None) -> SddConfig:' packages/ai-parrot/src/parrot/sdd/config.py)
# BEFORE — insert above `def load_sdd_config(root: Path | None = None) -> SddConfig:` (verified: config.py:106),
# i.e. directly after find_repo_root's body
DEFAULT_WORKTREE_ROOT: str = ".parrot/worktrees"
LEGACY_WORKTREE_ROOT: str = ".claude/worktrees"
WORKTREE_ROOT_ENV: str = "WORKTREE_BASE_PATH"


class LegacyWorktreesError(RuntimeError):
    """Registered git worktrees still live under ``.claude/worktrees/``; the message is the recipe."""


def worktree_root_setting(override: str | None = None) -> str:
    """Raw worktree root: ``override``, else ``$WORKTREE_BASE_PATH``, else ``DEFAULT_WORKTREE_ROOT``.

    Relative values are repository-relative POSIX strings without a trailing slash; absolute values are
    returned ``os.path.normpath``-ed. Blank values count as unset.
    """
    # FILL IN: pick the first non-blank of (override, os.environ.get(WORKTREE_ROOT_ENV)), else the default;
    #          absolute → os.path.normpath(value); relative → PurePosixPath-normalized string with no
    #          trailing "/" and no leading "./" — bounded by tests test_worktree_root_env_relative/_absolute.


def worktree_root(repo_root: Path, override: str | None = None) -> Path:
    """Absolute, normalized worktree root for ``repo_root`` (``repo_root / setting`` when relative)."""
    setting = worktree_root_setting(override)
    root = Path(setting) if os.path.isabs(setting) else Path(repo_root) / setting
    return Path(os.path.normpath(root.absolute()))


def legacy_worktrees(repo_root: Path) -> list[Path]:
    """Registered worktrees (``git worktree list --porcelain``) under ``repo_root/LEGACY_WORKTREE_ROOT``.

    Resolved paths, sorted. Empty when git is missing, the command fails, or ``repo_root`` is not a repo.
    Never raises.
    """
    legacy_root = (Path(repo_root) / LEGACY_WORKTREE_ROOT).resolve()
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    # FILL IN: parse every "worktree <path>" line, resolve it, keep those relative to legacy_root
    #          (excluding legacy_root itself), return sorted — bounded by test_legacy_worktrees_*.


def legacy_migration_recipe(repo_root: Path, paths: Sequence[Path]) -> list[str]:
    """Shell lines that move ``paths`` under ``worktree_root(repo_root)`` and repair git's bookkeeping.

    Map each old path to new_root / old.relative_to(legacy_root), preserving pool hierarchy.
    Reject overlapping old/new roots, duplicate destinations and occupied destinations
    (including dangling symlinks) before emitting a runnable recipe; raise ValueError with
    the conflicting paths. Installer/doctor keep their refusal and display that diagnostic.
    Repeat all collision checks at recipe execution before any move; abort on failure.
    Emit a fail-fast subshell, create destination parents and move only topmost registered
    ancestors once; registered descendants move with them. Never merge into an existing
    destination directory. Finally pass every mapped registration, including descendants,
    explicitly to ``git -C '<repo_root>' worktree repair '<new-1>' ... '<new-N>'``.
    Quote every path with ``shlex.quote``. An empty path list returns no commands.
    """
    if not paths:
        return []
    legacy_root = (Path(repo_root) / LEGACY_WORKTREE_ROOT).resolve()
    new_root = worktree_root(repo_root)
    # FILL IN: overlap check — new_root inside legacy_root or legacy_root inside new_root → ValueError
    # FILL IN: mapping old → new_root / old.relative_to(legacy_root); duplicates → ValueError
    # FILL IN: topmost = mapped olds with no mapped ancestor; for each topmost destination,
    #          os.path.lexists(dest) → ValueError naming it (dangling symlinks included)
    # FILL IN: emit lines: "(", "set -e", one `[ ! -e D ] && [ ! -L D ] || { echo "...: D" >&2; exit 1; }`
    #          per topmost destination (ALL checks before any mv), `mkdir -p <dest.parent>` + `mv <old> <dest>`
    #          per topmost, the repair line with every mapped new path (sorted), ")" — all paths shlex.quote'd.
```
**Why this shape**: The constants, signatures and docstrings are fixed by spec §2/§3 M1. `worktree_root`
uses `normpath(absolute())` rather than `resolve()` so a not-yet-existing root and a symlinked root
keep the configured spelling; classification code (TASK-5179) resolves when it compares.

### `packages/ai-parrot/tests/sdd/test_config.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    write_default_config,' packages/ai-parrot/tests/sdd/test_config.py)
# AFTER — extend the `from parrot.sdd.config import (` block (lines 11-19) with:
    DEFAULT_WORKTREE_ROOT,
    LEGACY_WORKTREE_ROOT,
    legacy_migration_recipe,
    legacy_worktrees,
    worktree_root,
    worktree_root_setting,
```
Append the new tests at the end of the file (see Test Specification). Add `import os`,
`import subprocess` at the top if missing.

### FILL IN checklist
- [ ] `worktree_root_setting` — precedence + normalization; bounded by tests env_relative/env_absolute/override_wins.
- [ ] `legacy_worktrees` — porcelain parse, resolved containment; bounded by test_legacy_worktrees_detects_registered / _no_git.
- [ ] `legacy_migration_recipe` — preflight + emitted recipe; bounded by AC5/AC6 and test_legacy_migration_*.

---

## Acceptance Criteria

- [ ] `from parrot.sdd.config import DEFAULT_WORKTREE_ROOT, LEGACY_WORKTREE_ROOT, WORKTREE_ROOT_ENV, LegacyWorktreesError, worktree_root_setting, worktree_root, legacy_worktrees, legacy_migration_recipe` works.
- [ ] Default `.parrot/worktrees`; relative env joins the repo root; absolute env is honoured normalized; blank env ignored; `override` beats env.
- [ ] `legacy_worktrees` lists only registered worktrees under the legacy root (a plain directory there is not listed) and returns `[]` outside a repository.
- [ ] Spec AC6 (recipe half): executing a generated recipe in a real repo with a feature, nested registered descendants and two pools sharing a worker suffix preserves hierarchy, leaves no legacy/prunable registrations, keeps branch HEADs and files; generation-time and execution-time collisions abort before any move.
- [ ] `parrot/sdd/config.py` imports no third-party package other than pydantic.
- [ ] `ruff check packages/ai-parrot/src/parrot/sdd/config.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_config.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_config.py — append

def _git_repo(tmp_path: Path) -> Path:
    """A real repo with one commit (worktrees need a commit)."""
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "dev", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "seed"], check=True)
    return repo


def test_worktree_root_default(tmp_path, monkeypatch): ...            # setting == DEFAULT_WORKTREE_ROOT; root == tmp_path/.parrot/worktrees
def test_worktree_root_env_relative(tmp_path, monkeypatch): ...       # WORKTREE_BASE_PATH=wt/x → "wt/x", tmp_path/wt/x
def test_worktree_root_env_absolute(tmp_path, monkeypatch): ...       # absolute (with "//" and "/./") normalized; "  " ignored
def test_worktree_root_override_wins(tmp_path, monkeypatch): ...
def test_legacy_worktrees_detects_registered(tmp_path, monkeypatch): ... # git worktree add .claude/worktrees/feat-FEAT-1-x → listed; mkdir .claude/worktrees/plain → not
def test_legacy_worktrees_no_git(tmp_path): ...                       # non-repo → []
def test_legacy_migration_recipe_shape(tmp_path, monkeypatch): ...     # "(" / "set -e" / preflight lines before first mv / topmost only / one repair line with all new paths / quoting with a space in repo path
def test_legacy_migration_collisions(tmp_path, monkeypatch): ...      # occupied dest, dangling symlink dest, override inside legacy root → ValueError; dest created AFTER generation → bash recipe exits non-zero and nothing moved
def test_legacy_migration_recipe_executes(tmp_path, monkeypatch): ... # feat + nested descendant + two pools "a--pool/w1","b--pool/w1"; run "\n".join(recipe) with bash; assert git worktree list --porcelain has no legacy/prunable, every branch HEAD unchanged, files present
```

---

## Agent Instructions

1. Work in the feature worktree: `parrot sdd worktree ensure --slug worktree-root-under-parrot --feature-id FEAT-802`.
2. Read the spec; this task has no dependencies.
3. Verify the Codebase Contract, then set this task `in-progress` in `sdd/tasks/index/worktree-root-under-parrot.json` and commit that file.
4. Implement from the blueprint; complete every `# FILL IN:`.
5. Run the Validation Commands with `PYTHONPATH=<abs worktree>/packages/ai-parrot/src`.
6. Commit only the listed files; close with `parrot sdd task close TASK-5174 worktree-root-under-parrot verified`; fill the Completion Note and commit.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
