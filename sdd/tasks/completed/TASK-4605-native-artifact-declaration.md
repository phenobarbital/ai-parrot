# TASK-4605: Declare native artifacts in pyproject.toml + venv-safe navrules wheel build

**Feature**: FEAT-722 — Worktree Native Artifact Sync
**Spec**: `sdd/specs/worktree-native-artifact-sync.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (declaration half). Every compiled artifact in this repo is
gitignored, so a fresh `git worktree add` carries none of them and
`import parrot.utils` fails inside a worktree (spec §1). The sync helper that
fixes this (TASK-4606 → TASK-4608) is driven by a **declaration**, not by
hardcoded globs — this task writes that declaration and the one build command
it needs that does not yet exist.

Two groups are declared: `cython-core` (built by
`packages/ai-parrot/setup.py`) and `navrules-pyo3` (a PyO3/maturin module).
Both are `autobuild = true` (spec §8 Q1, resolved 2026-10-22), but navrules'
only existing build path — `make build-rust` → `maturin develop --release`
(`packages/navrules/Makefile:9`) — **reinstalls navrules into the shared
`.venv`**, which `.claude/rules/worktree-management.md` §4 forbids. This task
adds `build-rust-wheel`: `maturin build --release --locked --out <tmp>` plus an
unpack of the wheel's single `.so`, which was measured end to end before this
task was written (13.7 s warm, exit 0, venv untouched; see Implementation Notes).

`--locked` is mandatory because the measured run **rewrote**
`packages/navrules/rust/Cargo.lock` (its `navrules_native` pin is stale at
`1.2.3` while `rust/Cargo.toml:3` says `1.2.4`). A worktree-creation step must
never silently edit a tracked file, so this task also refreshes that one line —
without it, every navrules auto-build would fail `--locked` and degrade to its
warning.

---

## Scope

- Append a `[tool.parrot.worktree]` table to the **root** `pyproject.toml`
  declaring `enabled` plus the two `[[tool.parrot.worktree.native_group]]`
  entries exactly as given in the Implementation Blueprint.
- Add a `build-rust-wheel` target to `packages/navrules/Makefile` and list it
  in `.PHONY`.
- Refresh `packages/navrules/rust/Cargo.lock`: the `navrules_native` entry's
  `version = "1.2.3"` → `"1.2.4"`. One line, nothing else.
- Write `tests/sdd_scripts/test_native_artifact_declaration.py` asserting the
  declaration's shape, that no automated path uses `maturin develop`, and that
  the lock pin matches the crate version.

**NOT in scope**: the `native_artifacts.py` module and its models/loader
(TASK-4606 — this task writes no Python outside the test file); any copying or
building logic; touching `ensure_worktree.py`, `worktree_manager.py` or
`baseline.py`; changing the existing `build-rust` target (it stays for humans);
running the actual navrules build (the AC only requires that the target exists
and is well-formed).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pyproject.toml` | MODIFY | Append the `[tool.parrot.worktree]` declaration |
| `packages/navrules/Makefile` | MODIFY | Add the `build-rust-wheel` target + `.PHONY` entry |
| `packages/navrules/rust/Cargo.lock` | MODIFY | Refresh the `navrules_native` pin to 1.2.4 |
| `tests/sdd_scripts/test_native_artifact_declaration.py` | CREATE | Declaration + build-plumbing contract tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import tomllib  # stdlib on requires-python ">=3.11,<3.14"  # verified: pyproject.toml:11
```

### Existing Signatures to Use
```toml
# pyproject.toml — tail of the file; the declaration is APPENDED after it
[tool.pylint.messages_control]          # line 299
[tool.mypy]                             # line 302
warn_unused_configs = true              # line 305 — LAST line of the file (verified)
```

```make
# packages/navrules/Makefile
.PHONY: build-rust test test-python cargo-test bench clean   # line 5 (occurrences: 1)
build-rust:                                                  # line 8 (occurrences: 1)
	uv run --with maturin maturin develop --release           # line 9 — the banned path
```

```toml
# packages/navrules/rust/Cargo.toml
name = "navrules_native"   # line 2
version = "1.2.4"          # line 3  <- the value the lock must match
[lib] name = "_navrules"   # lines 8-9
pyo3 = { version = "0.29", features = ["abi3-py311"] }  # line 13 — abi3: one .so covers 3.11-3.13
```

```toml
# packages/navrules/rust/Cargo.lock
name = "navrules_native"   # line 70 (occurrences: 1)
version = "1.2.3"          # line 71 — STALE, this task fixes it
```

### Does NOT Exist
- ~~`[tool.parrot]` or `[tool.parrot.worktree]` in any `pyproject.toml`~~ — this
  task writes the first one in the repo (`grep -rn '^\[tool\.parrot' --include=pyproject.toml .` ⇒ no hits).
- ~~`make -C packages/navrules build-rust-wheel`~~ — the target does not exist yet;
  only `build-rust`, `test`, `test-python`, `cargo-test`, `bench`, `clean` do.
- ~~`parrot.flows.dev_loop.native_artifacts`~~ — created by TASK-4606. **Do not
  import it from the test file in this task**; these tests read the TOML with
  `tomllib` directly, precisely so they pass before the module exists.
- ~~a `[tool.ruff]` table in `pyproject.toml`~~ — ruff is configured in
  `ruff.toml`; a `[tool.ruff]` table here is ignored (`pyproject.toml:297`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "pyproject.toml",
      "action": "MODIFY"
    },
    {
      "path": "packages/navrules/Makefile",
      "action": "MODIFY"
    },
    {
      "path": "packages/navrules/rust/Cargo.lock",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_native_artifact_declaration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Measured evidence (2026-10-22, before this task was written)

```
$ cd packages/navrules && uv run --no-sync --with maturin maturin build --release --out <tmp>
🔗 Found pyo3 bindings with abi3-py3.11 support
    Finished `release` profile [optimized] target(s) in 13.69s
📦 Built wheel for abi3 Python ≥ 3.11 to <tmp>/navrules-1.2.4-cp311-abi3-manylinux_2_34_x86_64.whl
EXIT=0
```
The wheel's only `.so` member is `navrules/_native/_navrules.abi3.so`, so
unpacking it with destination `src` lands exactly on
`src/navrules/_native/_navrules.abi3.so` (verified by extracting to a scratch
dir: 2 441 408 bytes, same size as the in-tree artifact). The run left
`navrules.pth`, the venv's navrules dist-info and the in-tree `.so`
(mtime 2026-10-16) untouched — but it DID rewrite `rust/Cargo.lock`, which is
why the target passes `--locked`.

The unpack one-liner was executed as written below and exited 0.

### Key Constraints
- The declaration is **appended at end of file**. Do NOT insert it before
  `[tool.pylint.messages_control]`: `[[tool.parrot.worktree.native_group]]` is
  an array-of-tables, and placing it mid-file would make every following
  key land inside the last `native_group` entry instead of its own table.
  (This supersedes the spec §6 Edit Sites row's anchor, which named
  `[tool.pylint.messages_control]`; the fresh verified anchor is the file's
  last line, `warn_unused_configs = true`, `pyproject.toml:305`, occurrences 1.)
- Makefile recipes are TAB-indented. `$$` in a recipe is a literal `$`.
- Do not reformat, reorder or re-pin anything else in `Cargo.lock`.

---

## Delegation Contract

```json
{
  "schema_version": 1,
  "task_id": "TASK-4605",
  "spec_path": "sdd/specs/worktree-native-artifact-sync.spec.md",
  "design_complete": true,
  "targets": [
    {
      "path": "pyproject.toml",
      "action": "modify",
      "expected_sha256": "8b0a0590dba2379afb8be430998aab2e2205e1fdc18f17ca1cd5ae8efc501840",
      "planned_changes": "Append the [tool.parrot.worktree] declaration with both native_group entries",
      "blocks": ["impl-pyproject-table"]
    },
    {
      "path": "packages/navrules/Makefile",
      "action": "modify",
      "expected_sha256": "99ae741b62cd88b822254f10742276608c05fa595abb7989d7c576baf813cda2",
      "planned_changes": "Add build-rust-wheel target and extend .PHONY",
      "blocks": ["impl-makefile-phony", "impl-makefile-target"]
    },
    {
      "path": "packages/navrules/rust/Cargo.lock",
      "action": "modify",
      "expected_sha256": "7deba67eee18b09c22eb966bc2d9e66181acdfa671da5048bc0a46087c78f20e",
      "planned_changes": "Refresh the navrules_native pin from 1.2.3 to 1.2.4",
      "blocks": ["impl-cargo-lock"]
    },
    {
      "path": "tests/sdd_scripts/test_native_artifact_declaration.py",
      "action": "create",
      "expected_sha256": null,
      "planned_changes": "New contract tests for the declaration and the build plumbing",
      "blocks": ["impl-declaration-tests"]
    }
  ],
  "references": [
    {
      "path": "packages/navrules/rust/Cargo.toml",
      "sha256": "2cca226c2927d79ace1428932586ddd8f04e3e269e090059eb5dd82296321432",
      "start_line": 1,
      "end_line": 14,
      "purpose": "crate name/version the lock must match (re-read at execution time)"
    }
  ],
  "implementation_blocks": [
    "impl-pyproject-table",
    "impl-makefile-phony",
    "impl-makefile-target",
    "impl-cargo-lock",
    "impl-declaration-tests"
  ],
  "acceptance_criteria": [
    "pytest tests/sdd_scripts/test_native_artifact_declaration.py passes",
    "git diff --stat shows exactly 3 modified files plus 1 new test file"
  ],
  "validation_commands": [
    ["pytest", "tests/sdd_scripts/test_native_artifact_declaration.py", "-q"]
  ]
}
```

> Every digest in this packet is real, computed with `sha256sum` at
> `/sdd-task` time against `a99dd4fe9`. Hashes are re-validated at execution
> time: if one has drifted by then, refresh the packet in THIS file first, then
> re-run the writer — never relax or delete the hash.

---

## Implementation Blueprint

### Steps (in order)
1. Append the declaration to `pyproject.toml` — *why*: it is the single source
   of truth the sync helper reads; appending keeps the array-of-tables from
   swallowing later keys.
2. Add `build-rust-wheel` to `packages/navrules/Makefile` and extend `.PHONY`
   — *why*: the manifest's navrules `build` argv names this target, and it is
   the only navrules build path that never writes into the shared `.venv`.
3. Refresh the `Cargo.lock` pin — *why*: `--locked` fails against a stale lock,
   which would make the navrules auto-build permanently degrade to a warning.
4. Write the contract tests — *why*: the declaration is config, so only a test
   keeps a future edit from quietly re-introducing `maturin develop` or
   desyncing the lock.

### `pyproject.toml` (MODIFY)
```toml id=impl-pyproject-table
# occurrences: 1 (verified: grep -c '^warn_unused_configs = true$' pyproject.toml)
# AFTER — append at END OF FILE, below `warn_unused_configs = true` (verified: pyproject.toml:305)

[tool.parrot.worktree]
# Native build artifacts a fresh `git worktree add` cannot carry, because every
# one of them is gitignored. `ensure_worktree` and the sdd-coder pool copy these
# from the main checkout into a new worktree before any agent runs in it, and
# build them there when they are missing (FEAT-722).
enabled = true

[[tool.parrot.worktree.native_group]]
name = "cython-core"
copy_globs = ["packages/ai-parrot/src/parrot/**/*.so"]
pair_sources = ["packages/ai-parrot/src/parrot/**/*.pyx"]
abi_scoped = true
autobuild = true
build = ["{python}", "setup.py", "build_ext", "--inplace"]
build_cwd = "packages/ai-parrot"
build_timeout_s = 900
manual_hint = "cd packages/ai-parrot && python setup.py build_ext --inplace"

[[tool.parrot.worktree.native_group]]
name = "navrules-pyo3"
copy_globs = ["packages/navrules/src/navrules/_native/*.so"]
required = true
# abi3-py311: one .so covers CPython 3.11-3.13, so presence is NOT ABI-scoped.
abi_scoped = false
autobuild = true
# `build-rust-wheel`, never the Makefile's `build-rust` (= `maturin develop`,
# which reinstalls navrules into the SHARED venv — banned in automated paths).
build = ["make", "-C", "packages/navrules", "build-rust-wheel"]
build_timeout_s = 900
manual_hint = "make -C packages/navrules build-rust-wheel"
```
**Why this shape**: `copy` is what gets synced, `pair_sources` is how a missing
Cython artifact is detected (each `.pyx` needs a sibling compiled module),
`abi_scoped` distinguishes per-interpreter `.so`s from abi3 ones, and
`build`/`build_cwd` are an argv + cwd so the helper never needs a shell.
`{python}` is substituted with `sys.executable` by TASK-4608. Do NOT change the
group names — TASK-4606's tests and the lock filenames derive from them.

### `packages/navrules/Makefile` (MODIFY — 1 of 2)
```make id=impl-makefile-phony
# occurrences: 1 (verified: grep -c '.PHONY: build-rust test test-python cargo-test bench clean' packages/navrules/Makefile)
# REPLACE the line `.PHONY: build-rust test test-python cargo-test bench clean` (verified: Makefile:5)
.PHONY: build-rust build-rust-wheel test test-python cargo-test bench clean
```
**Why**: a non-file target must be phony or `make` may skip it when a
same-named file appears.

### `packages/navrules/Makefile` (MODIFY — 2 of 2)
```make id=impl-makefile-target
# occurrences: 1 (verified: grep -c 'build-rust:' packages/navrules/Makefile)
# AFTER — insert below the `build-rust:` recipe, i.e. after its
# `uv run --with maturin maturin develop --release` line (verified: Makefile:8-9)

# Build the Rust extension as a wheel and unpack ONLY its .so into src/,
# installing nothing into the active environment (FEAT-722). `maturin develop`
# would reinstall navrules into the SHARED venv, which worktree agents must
# never mutate; `--locked` guarantees an automated build never rewrites
# rust/Cargo.lock. Recipe lines are TAB-indented; `$$` is a literal `$`.
build-rust-wheel:
	@tmp=$$(mktemp -d) && \
		uv run --no-sync --with maturin maturin build --release --locked --out "$$tmp" && \
		uv run --no-sync python -c 'import glob,sys,zipfile; w=glob.glob(sys.argv[1]+"/*.whl")[0]; z=zipfile.ZipFile(w); [z.extract(n, sys.argv[2]) for n in z.namelist() if n.endswith(".so")]' "$$tmp" src && \
		rm -rf "$$tmp"
```
**Why**: both commands above were run verbatim on 2026-10-22 and exited 0; the
unpack places the wheel's `navrules/_native/_navrules.abi3.so` at
`src/navrules/_native/_navrules.abi3.so`, which is exactly the path the
`navrules-pyo3` group's `copy` glob matches. Keep `--locked`, keep
`--no-sync`, and do not collapse the `&& \` chain into separate recipe lines
(each line would otherwise run in its own shell and lose `$$tmp`).

### `packages/navrules/rust/Cargo.lock` (MODIFY)
```toml id=impl-cargo-lock
# occurrences: 1 (verified: grep -c 'name = "navrules_native"' packages/navrules/rust/Cargo.lock)
# REPLACE the `version` line directly below `name = "navrules_native"` (verified: Cargo.lock:70-71)
name = "navrules_native"
version = "1.2.4"
```
**Why**: `rust/Cargo.toml:3` is already `1.2.4`; the lock lagging at `1.2.3` is
what makes a `--locked` build fail today. Change this value only — no
dependency re-resolution, no reordering.

### `tests/sdd_scripts/test_native_artifact_declaration.py` (CREATE)
```python id=impl-declaration-tests path=tests/sdd_scripts/test_native_artifact_declaration.py
"""Contract tests for the [tool.parrot.worktree] native-artifact declaration (FEAT-722).

These read the TOML and the Makefile directly — never
`parrot.flows.dev_loop.native_artifacts`, which TASK-4606 adds — so the
declaration is gated independently of the helper that consumes it.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NAVRULES = REPO_ROOT / "packages" / "navrules"


def _worktree_table() -> dict:
    """The parsed ``[tool.parrot.worktree]`` table of the root pyproject.toml."""
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["tool"]["parrot"]["worktree"]


def _group(name: str) -> dict:
    """The declared native group called ``name``."""
    return next(group for group in _worktree_table()["native_group"] if group["name"] == name)


def _makefile_recipe(target: str) -> str:
    """The TAB-indented recipe lines of ``target`` in the navrules Makefile."""
    lines = (NAVRULES / "Makefile").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
    recipe: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        recipe.append(line)
    return "\n".join(recipe)


def test_table_declares_both_groups() -> None:
    table = _worktree_table()
    assert table["enabled"] is True
    assert [group["name"] for group in table["native_group"]] == ["cython-core", "navrules-pyo3"]


def test_every_group_is_autobuildable() -> None:
    """Spec §8 Q1: both groups build automatically when their artifact is missing."""
    for group in _worktree_table()["native_group"]:
        assert group["autobuild"] is True, group["name"]
        assert group["build"], group["name"]
        assert group["manual_hint"], group["name"]


def test_cython_group_pairs_sources_with_artifacts() -> None:
    group = _group("cython-core")
    assert group["copy_globs"] == ["packages/ai-parrot/src/parrot/**/*.so"]
    assert group["pair_sources"] == ["packages/ai-parrot/src/parrot/**/*.pyx"]
    assert group["abi_scoped"] is True
    assert group["build"] == ["{python}", "setup.py", "build_ext", "--inplace"]
    assert group["build_cwd"] == "packages/ai-parrot"


def test_navrules_group_targets_the_wheel_build() -> None:
    group = _group("navrules-pyo3")
    assert group["copy_globs"] == ["packages/navrules/src/navrules/_native/*.so"]
    assert group["abi_scoped"] is False
    assert group["build"] == ["make", "-C", "packages/navrules", "build-rust-wheel"]


def test_navrules_wheel_target_never_installs_into_the_shared_venv() -> None:
    """`maturin develop` reinstalls navrules into the active env — banned here."""
    recipe = _makefile_recipe("build-rust-wheel")
    assert "maturin build" in recipe
    assert "--locked" in recipe
    assert "maturin develop" not in recipe


def test_cargo_lock_pins_the_current_crate_version() -> None:
    """A `--locked` build fails unless the lock matches rust/Cargo.toml."""
    cargo_toml = (NAVRULES / "rust" / "Cargo.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version = "([^"]+)"', cargo_toml, re.MULTILINE)
    assert declared is not None
    locked = re.search(r'name = "navrules_native"\nversion = "([^"]+)"', (NAVRULES / "rust" / "Cargo.lock").read_text(encoding="utf-8"))
    assert locked is not None
    assert locked.group(1) == declared.group(1)
```
**Why this shape**: the helpers are defined before use so the module reads top
to bottom; every assertion pins a value the sync helper will later depend on by
name (group names, `copy`, `pair_sources`, `abi_scoped`, `build`). The
`maturin develop` and lock-pin tests are the two regressions that would be
silent otherwise.

### FILL IN checklist
- [ ] none — every block above is complete, decided code. If a block does not
      apply cleanly, STOP and report the drift rather than improvising.

---

## Acceptance Criteria

- [ ] `python -c "import tomllib,pathlib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['tool']['parrot']['worktree']['native_group'][1]['name'])"` prints `navrules-pyo3`
- [ ] `make -C packages/navrules -n build-rust-wheel` prints the recipe without error
- [ ] `grep -n 'maturin develop' packages/navrules/Makefile` matches only the
      pre-existing `build-rust` recipe (line 9), never `build-rust-wheel`
- [ ] The `navrules_native` block in `rust/Cargo.lock` reads `version = "1.2.4"`
- [ ] `pytest tests/sdd_scripts/test_native_artifact_declaration.py -q` passes
- [ ] `git status --porcelain` shows only the four files this task lists
- [ ] No linting errors: `ruff check tests/sdd_scripts/test_native_artifact_declaration.py`

---

## Validation Commands

- `pytest tests/sdd_scripts/test_native_artifact_declaration.py -q`

---

## Test Specification

The complete test module is given verbatim in the Implementation Blueprint
(`tests/sdd_scripts/test_native_artifact_declaration.py`) — write it as shown.
No additional fixtures are required; the tests read repository files directly
and need neither a git sandbox nor a built extension.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug worktree-native-artifact-sync --feature-id FEAT-722`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — before writing ANY code, re-run each
   `grep -c` quoted in the blueprint blocks; a count of 0 means the anchor
   moved, so STOP and report instead of inventing an attachment point
5. **Update status** in `sdd/tasks/index/worktree-native-artifact-sync.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — write the blueprint blocks as given; this task has no
   `FILL IN` markers by design
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the four files this task lists
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4605 worktree-native-artifact-sync verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (orchestrator) — seat: gpt-5.6-terra (codex), 1 attempt
**Date**: 2026-10-22
**Notes**: Declared [tool.parrot.worktree] with cython-core and navrules-pyo3 groups, added build-rust-wheel Makefile target (maturin build --locked, no develop), refreshed Cargo.lock pin to 1.2.4. tests/sdd_scripts/test_native_artifact_declaration.py: 6 passed.

**Deviations from spec**: none
