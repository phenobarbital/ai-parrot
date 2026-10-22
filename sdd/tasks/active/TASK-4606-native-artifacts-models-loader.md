# TASK-4606: native_artifacts models + manifest loader

**Feature**: FEAT-722 — Worktree Native Artifact Sync
**Spec**: `sdd/specs/worktree-native-artifact-sync.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4605
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (parser half). TASK-4605 wrote the `[tool.parrot.worktree]`
declaration; this task creates the module that reads it and the Pydantic models
every later task in this feature consumes. Nothing in this task copies or
builds anything — TASK-4607 adds the copy engine on top of these models, and
TASK-4608 the auto-build.

The module deliberately imports **nothing from the rest of `parrot`** (stdlib +
pydantic only), because three unrelated callers must be able to import it
without an import cycle: `parrot.flows.dev_loop.worktree_manager`,
`parrot.flows.dev_loop.test_scope.baseline` and `scripts.sdd.ensure_worktree`
(spec §7 Patterns to Follow).

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py`
  with the module docstring, the four Pydantic models (`NativeGroup`,
  `NativeManifest`, `MissingArtifact`, `NativeSyncReport`), the module
  constants, the two env-var predicates, and `load_manifest()`.
- Create `packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py`
  with the loader and model tests listed in Test Specification.

**NOT in scope**: `main_checkout_root`, `missing_artifacts`,
`sync_native_artifacts` (TASK-4607); `build_missing` and the file lock
(TASK-4608); any caller wiring (TASK-4609/4610/4611). Do not add a hardcoded
copy of the declared groups as a Python default — an absent table means
"nothing declared" by design.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py` | CREATE | Models, constants and `load_manifest()` |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py` | CREATE | Loader + model unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations          # repo-wide convention
import os, tomllib                          # tomllib: stdlib on >=3.11  # verified: pyproject.toml:11
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field  # verified: packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py:32
```
Installed pydantic is **2.14.1** (verified 2026-10-22), so `ConfigDict` /
`model_config` / `model_validate` are all available.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py
from pydantic import BaseModel, Field   # line 32 — the sibling module's import style
class MergeReport(BaseModel):            # line 62 — plain BaseModel + Field(default_factory=list)
    merged: List[str] = Field(default_factory=list)   # line 76
```

```toml
# The table this task parses (written by TASK-4605, root pyproject.toml)
[tool.parrot.worktree]
enabled = true
[[tool.parrot.worktree.native_group]]   # an ARRAY OF TABLES -> list[dict]
name = "cython-core"
copy_globs = [...]
pair_sources = [...]
abi_scoped = true
autobuild = true
build = ["{python}", "setup.py", "build_ext", "--inplace"]
build_cwd = "packages/ai-parrot"
build_timeout_s = 900
manual_hint = "..."
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop.native_artifacts`~~ — THIS task creates it. Nothing
  imports it yet; do not edit any other module to register it.
- ~~a `copy` field~~ — the field is `copy_globs`. A Pydantic field literally
  named `copy` shadows `BaseModel.copy` and emits a `UserWarning`, and this
  repo runs pytest with `filterwarnings = ["error"]` (`pyproject.toml:259`),
  so it would fail collection. Never rename it back.
- ~~`parrot.flows.dev_loop.procs.git_env` / `run_bounded`~~ — they exist
  (`worktree_manager.py:34`) but are NOT used here: this module must not
  import anything from `parrot`.
- ~~`filelock.FileLock`~~ — installed (4.2.0) but unused; the repo's
  cross-process idiom is a guarded `import fcntl`
  (`test_scope/green_cache.py:24-27`), and it belongs to TASK-4608 anyway.
- ~~`tomli`~~ — not needed and not a dependency; `tomllib` is stdlib here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")` on every
  model: a typo in the declaration must raise, not be ignored.
- `load_manifest` raises `ValueError` (never a bare `ValidationError`) so
  callers have one exception type to catch; chain with `from exc`.
- `[[tool.parrot.worktree.native_group]]` parses as `table["native_group"]`,
  a `list[dict]` — `NativeManifest` has no `native_group` field, so map it to
  `groups` explicitly instead of splatting the table.
- No logging in this task: the module's logger is introduced with the first
  behaviour that can warn (TASK-4607).

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py:62-77` —
  the Pydantic report-model style this module follows.
- `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:1-5` —
  the "stdlib only, importable from anywhere" module docstring convention.

---

## Implementation Blueprint

### Steps (in order)
1. Create the module with its docstring, constants, env predicates and the four
   models — *why*: every later task in this feature imports these names, so
   they are fixed here and not renegotiable.
2. Add `load_manifest()` — *why*: it is the only reader of the declaration;
   centralising it keeps the TOML shape in one place.
3. Write the tests — *why*: the loader's two failure modes (absent table,
   malformed table) are the ones a later refactor would silently break.

### `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py` (CREATE)
```python
"""Native build artifacts a worktree cannot carry, because they are gitignored (FEAT-722).

Every compiled artifact in this repository is ignored by git, so a fresh
``git worktree add`` produces a tree in which ``import parrot.utils`` fails
(``parrot/utils/__init__.py`` imports the Cython ``.types`` module). The
artifacts are therefore DECLARED in the root ``pyproject.toml`` under
``[tool.parrot.worktree]`` and copied from the main checkout into each new
worktree.

This module imports only the standard library and pydantic: ``ensure_worktree``,
``worktree_manager`` and ``test_scope.baseline`` all import it, so it must not
pull in the rest of ``parrot``.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Directory (relative to the main checkout) holding the per-group build locks.
LOCK_DIRNAME: str = ".parrot/locks"
#: Set to "0" to disable the whole native sync.
SYNC_ENV_VAR: str = "PARROT_WORKTREE_SYNC_NATIVE"
#: Set to "0" to copy what exists but never build what is missing.
AUTOBUILD_ENV_VAR: str = "PARROT_WORKTREE_AUTOBUILD"
#: Replaced with ``sys.executable`` in a group's ``build`` argv (TASK-4608).
PYTHON_PLACEHOLDER: str = "{python}"


class NativeGroup(BaseModel):
    """One family of native build artifacts declared in ``[tool.parrot.worktree]``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    copy_globs: list[str] = Field(default_factory=list)
    pair_sources: list[str] = Field(default_factory=list)
    required: bool = True
    abi_scoped: bool = False
    autobuild: bool = False
    build: list[str] = Field(default_factory=list)
    build_cwd: str = "."
    build_timeout_s: int = 900
    manual_hint: str | None = None


class NativeManifest(BaseModel):
    """The parsed ``[tool.parrot.worktree]`` table."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    groups: list[NativeGroup] = Field(default_factory=list)


class MissingArtifact(BaseModel):
    """A declared artifact that is absent from the main checkout."""

    model_config = ConfigDict(extra="forbid")

    group: str
    reason: Literal["no_match", "unpaired_source", "abi_mismatch"]
    detail: str


class NativeSyncReport(BaseModel):
    """Outcome of one sync. Never an exception carrier — callers decide severity."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    copied: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    built: list[str] = Field(default_factory=list)
    missing: list[MissingArtifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def env_flag_disabled(name: str) -> bool:
    """True when environment variable ``name`` is explicitly set to "0"."""
    return os.environ.get(name, "").strip() == "0"


def load_manifest(repo_root: Path) -> NativeManifest:
    """Parse ``[tool.parrot.worktree]`` from ``repo_root/pyproject.toml``.

    Returns an EMPTY manifest (``groups=[]``, so a sync is a no-op) when the
    file or the table is absent — the declaration is the single source of truth
    and is never duplicated here.

    Raises:
        ValueError: The table exists but is malformed (unknown key, wrong type).
    """
    pyproject = Path(repo_root) / "pyproject.toml"
    if not pyproject.is_file():
        return NativeManifest()
    with pyproject.open("rb") as handle:
        table = tomllib.load(handle).get("tool", {}).get("parrot", {}).get("worktree")
    if not table:
        return NativeManifest()
    # FILL IN: build the manifest from `table` — map `native_group` (a list of
    # dicts, because it is a TOML array of tables) onto `groups`, pass `enabled`
    # through, and re-raise any pydantic ValidationError as
    # ValueError(f"invalid [tool.parrot.worktree] in {pyproject}: {exc}") from exc.
    # Bounded by: extra="forbid" must stay in force (AC: malformed table raises).
    raise NotImplementedError
```
**Why this shape**: the models are the feature's whole vocabulary — TASK-4607
through TASK-4611 import these exact names, so no field may be renamed or
dropped. `env_flag_disabled` is deliberately one generic predicate rather than
two near-identical functions, because both env vars share the "explicitly 0"
semantics (an unset or empty variable must NOT disable anything). Only the
manifest-construction body is left to fill in; the signature, the return type
and the two early returns are fixed.

### FILL IN checklist
- [ ] `native_artifacts.py::load_manifest` — construct `NativeManifest` from the
      parsed table and translate `ValidationError` into `ValueError`; bounded by
      "absent table ⇒ empty manifest, malformed table ⇒ ValueError" (AC 2-4).

---

## Acceptance Criteria

- [ ] `from parrot.flows.dev_loop.native_artifacts import NativeGroup, NativeManifest, MissingArtifact, NativeSyncReport, load_manifest, env_flag_disabled` works
- [ ] `load_manifest(Path("."))` on the repo root returns a manifest whose
      `groups` names are `["cython-core", "navrules-pyo3"]` and whose
      `enabled` is `True`
- [ ] `load_manifest()` on a tmp dir with no `pyproject.toml`, and on one whose
      `pyproject.toml` has no `[tool.parrot.worktree]`, both return
      `NativeManifest(enabled=True, groups=[])`
- [ ] A table with an unknown key inside a group raises `ValueError` (not
      `ValidationError`, not a silent default)
- [ ] The module imports nothing from `parrot`:
      `grep -nE '^(from|import) parrot' packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py`
      returns nothing
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py -q` passes
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py
"""Tests for parrot.flows.dev_loop.native_artifacts (FEAT-722)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.flows.dev_loop.native_artifacts import (
    AUTOBUILD_ENV_VAR,
    SYNC_ENV_VAR,
    NativeGroup,
    NativeManifest,
    env_flag_disabled,
    load_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_load_manifest_reads_declared_groups() -> None:
    """The real declaration parses into both groups, in order."""
    manifest = load_manifest(REPO_ROOT)
    assert manifest.enabled is True
    assert [group.name for group in manifest.groups] == ["cython-core", "navrules-pyo3"]
    cython = manifest.groups[0]
    assert cython.abi_scoped is True
    assert cython.autobuild is True
    assert cython.build_cwd == "packages/ai-parrot"
    assert cython.pair_sources == ["packages/ai-parrot/src/parrot/**/*.pyx"]


def test_load_manifest_empty_when_file_absent(tmp_path: Path) -> None:
    assert load_manifest(tmp_path) == NativeManifest(enabled=True, groups=[])


def test_load_manifest_empty_when_table_absent(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert load_manifest(tmp_path).groups == []


def test_load_manifest_rejects_malformed_table(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.parrot.worktree]\nenabled = true\n"
        '[[tool.parrot.worktree.native_group]]\nname = "x"\nbogus_key = 1\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_manifest(tmp_path)


def test_group_defaults() -> None:
    group = NativeGroup(name="g")
    assert group.required is True
    assert group.abi_scoped is False
    assert group.autobuild is False
    assert group.build == []
    assert group.build_cwd == "."
    assert group.build_timeout_s == 900
    assert group.manual_hint is None


def test_env_flag_disabled_only_on_explicit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SYNC_ENV_VAR, raising=False)
    assert env_flag_disabled(SYNC_ENV_VAR) is False
    monkeypatch.setenv(SYNC_ENV_VAR, "")
    assert env_flag_disabled(SYNC_ENV_VAR) is False
    monkeypatch.setenv(SYNC_ENV_VAR, "1")
    assert env_flag_disabled(SYNC_ENV_VAR) is False
    monkeypatch.setenv(AUTOBUILD_ENV_VAR, "0")
    assert env_flag_disabled(AUTOBUILD_ENV_VAR) is True
```

`REPO_ROOT` resolution: the test file is at
`packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py`, so
`parents[0]=dev_loop`, `[1]=flows`, `[2]=tests`, `[3]=ai-parrot`,
`[4]=packages` — **verify this at implementation time** and use the index that
actually lands on the repository root (`parents[5]`) if `packages` is one level
higher than assumed. The test must not hardcode an absolute path.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug worktree-native-artifact-sync --feature-id FEAT-722`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-4605 must be `"done"` in
   `sdd/tasks/index/worktree-native-artifact-sync.json`; `load_manifest`'s first
   test reads the table that task writes
4. **Verify the Codebase Contract** — confirm the `[tool.parrot.worktree]` table
   is present in the root `pyproject.toml` and that its group keys match the
   `NativeGroup` fields exactly; a mismatch means TASK-4605 drifted, so fix the
   contract first
5. **Update status** in `sdd/tasks/index/worktree-native-artifact-sync.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the blueprint block, complete the single
   `# FILL IN:` marker, and never rename a model field
7. **Verify** all acceptance criteria are met — run the Validation Commands
   with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the two files this task lists
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4606 worktree-native-artifact-sync verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
