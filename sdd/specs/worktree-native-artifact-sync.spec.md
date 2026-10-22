---
type: feature
base_branch: dev
projects: [sdd-tooling, dev-loop, ai-parrot, navrules]
tags: [worktree, native-extensions, cython, build, sdd-worker]
---

# Feature Specification: Worktree Native Artifact Sync

**Feature ID**: FEAT-722
**Date**: 2026-10-22
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.2.5

---

## 1. Motivation & Business Requirements

### Problem Statement

A fresh SDD worktree cannot run the code it was created to change, because
every compiled native artifact in this repository is gitignored and therefore
absent from `git worktree add`.

Verified on `add1f89ea` (2026-10-22):

1. **A worktree holds zero `.so` files.**
   `find .claude/worktrees/feat-FEAT-682-scraping-executor-fixes/packages -name '*.so'`
   returns nothing, while the main checkout holds five in-tree artifacts.
2. **The failure is not limited to the Cython module — it kills `parrot.utils`
   itself.** `packages/ai-parrot/src/parrot/utils/__init__.py:1` is
   `from .types import SafeDict`, so with the documented worktree prefix
   (`PYTHONPATH=packages/ai-parrot/src`, `.claude/rules/worktree-management.md:52`)
   even `import parrot.utils` raises:
   ```
   File ".../feat-FEAT-682-scraping-executor-fixes/packages/ai-parrot/src/parrot/utils/__init__.py", line 1
       from .types import SafeDict
   ModuleNotFoundError: No module named 'parrot.utils.types'
   ```
3. **Agents pay for this every run.** `sdd-worker` sessions repeatedly report
   *"Inside the worktree the compiled `parrot.utils.types` module is missing,
   which is the known worktree limitation"*, then improvise a one-off copy or
   silently fall back to testing main-checkout code — the hazard already
   recorded in the project memory note *worktree-tests-run-main-checkout-code*.
4. **The capability already exists but is not shared.**
   `prepare_baseline_checkout()`
   (`packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py:45-76`)
   copies `packages/*/src/**/*.so` from the main checkout into its detached
   baseline checkout and refuses the checkout when a `.pyx` has no sibling
   `.so`. Neither worktree-creation path calls it.

### Goals

- Every worktree created through the repository's own tooling can `import
  parrot.utils` (and run that package's tests) without an agent copying
  anything by hand.
- The artifacts a worktree needs are **declared**, in one readable place
  (root `pyproject.toml`), rather than hardcoded in each caller.
- A declared artifact that is missing from the main checkout is **built
  automatically** (user decision, 2026-10-22) — for **both** groups,
  concurrency-safely, for the running interpreter only, and without mutating
  the shared `.venv` or any tracked file.
- Native sync never becomes a new way for worktree creation to fail: a
  failed build degrades to a warning that names the exact manual command.
- `baseline.py`'s hand-rolled copy loop is replaced by the shared helper —
  one implementation, not two.

### Non-Goals (explicitly out of scope)

- Making worktrees self-contained Python environments. The shared `.venv`
  stays editable-installed against the main checkout; `PYTHONPATH=packages/<dist>/src`
  remains the documented way to import worktree code.
- Building or copying `parrot_codec`. It is installed as a real,
  non-editable wheel at
  `.venv/lib/python3.12/site-packages/parrot_codec/parrot_codec.cpython-312-x86_64-linux-gnu.so`,
  so it already resolves from inside any worktree.
- Building or installing `yaml_rs` (`packages/ai-parrot/src/parrot/yaml-rs/Cargo.toml`).
  It is not built and not importable anywhere today (`import yaml_rs` →
  `ModuleNotFoundError`); wiring it up is a separate concern.
- Installing anything into the shared `.venv`. The navrules PyO3 module **is**
  auto-built (§8 Q1, revised 2026-10-22), but never with
  `maturin develop --release` (`packages/navrules/Makefile:9`), which
  reinstalls navrules into the active environment — forbidden by
  `.claude/rules/worktree-management.md` §4 and the cause of two past
  breakages. The new `build-rust-wheel` target builds a wheel to a temp dir
  and unpacks only its `.so`; `maturin develop` stays out of every automated
  path.
- Tracking `.so` files in git, or removing them from `.gitignore`.
- Changing `/sdd-done`, `remove_worktree.py`, or any worktree-removal path.

---

## 2. Architectural Design

### Overview

One new stdlib+pydantic module, `parrot.flows.dev_loop.native_artifacts`, owns
the whole concern:

- **Declaration.** The root `pyproject.toml` grows a `[tool.parrot.worktree]`
  table with one `[[tool.parrot.worktree.native_group]]` entry per family of
  native artifacts (today: `cython-core`, `navrules-pyo3`). Each group declares
  the globs to copy, the sources whose presence makes an artifact mandatory,
  whether it may be auto-built, and the argv of its build command. `tomllib`
  is stdlib on this repo's floor (`requires-python = ">=3.11,<3.14"`,
  `pyproject.toml:11`).
- **Sync.** `sync_native_artifacts()` resolves the declared globs against the
  **main checkout**, copies each match to the same repo-relative path inside
  the target worktree, and skips a destination whose size and mtime already
  match. It is idempotent, so it is safe to re-run on worktree *reuse* (where
  it acts as a top-up after a rebuild).
- **Auto-build.** When a group's declared source exists but its artifact does
  not, and the group is `autobuild = true`, the helper takes an exclusive
  `fcntl.flock` on `<main_root>/.parrot/locks/native-<group>.lock`, re-checks
  (another worktree creation may have just built it), runs the declared argv
  in the main checkout, and then copies. A build failure or timeout is a
  warning carrying the manual command — never an exception. Both declared
  groups are auto-buildable: `cython-core` via `setup.py build_ext --inplace`,
  `navrules-pyo3` via the new `make -C packages/navrules build-rust-wheel`,
  which is `maturin build --release --locked --out <tmp>` plus an unpack of the
  wheel's single `.so` — measured end to end at **13.7 s** with a warm cargo
  target, exit 0, wheel payload exactly `navrules/_native/_navrules.abi3.so`
  (verified 2026-10-22). `--locked` is what keeps an automated build from ever
  rewriting the tracked `rust/Cargo.lock`.
- **Wiring.** Both worktree-creation paths call it, and `baseline.py` is
  refactored onto it:
  | Caller | When |
  |---|---|
  | `scripts/sdd/ensure_worktree.py` `main()` | right after `ensure()` returns, for created and reused worktrees alike — feature, hotfix and `/sdd-brief` worktrees, i.e. `/sdd-start`, `sdd-worker`, `sdd-planner`, `sdd-research`, `sdd-autopilot` |
  | `SubWorktreeManager.create()` | after `git worktree add` succeeds — every per-attempt `sdd-coder` pool sub-worktree |
  | `prepare_baseline_checkout()` | replaces its own `.so` glob loop; keeps its hard `BaselineUnavailable` on a missing artifact |

Artifacts stay **untracked** in the worktree (they are gitignored), so no
commit, status entry, or `/sdd-done` cleanliness check is affected.

### Component Diagram

```
root pyproject.toml  [tool.parrot.worktree]
          │ load_manifest()
          ▼
 parrot.flows.dev_loop.native_artifacts
   ├── load_manifest()            → NativeManifest
   ├── missing_artifacts()        → list[MissingArtifact]
   ├── build_missing()            → flock + argv in main checkout
   └── sync_native_artifacts()    → NativeSyncReport
          ▲                ▲                  ▲
          │                │                  │
scripts/sdd/        SubWorktreeManager   test_scope/baseline.py
ensure_worktree       .create()          prepare_baseline_checkout()
  .main()           (coder sub-worktree)   (hard-fails on missing)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `scripts.sdd.ensure_worktree.main()` | calls | right after `ensure()` returns — which covers the create **and** the reuse path with one call site, and leaves `ensure()`'s published `tuple[Path, bool]` contract (and its 14 existing test call sites) untouched. Adds a `native` key to `--json`. **stdout stays exactly the worktree path** — callers do `WORKTREE_PATH=$(python -m scripts.sdd.ensure_worktree …)` (`.claude/agents/sdd-worker.md:251`); warnings go to stderr |
| `SubWorktreeManager.create()` | calls | via `asyncio.to_thread` (the helper is blocking I/O); failures logged, never raised — a native-sync problem must not fail a coder attempt |
| `parrot.flows.dev_loop.test_scope.baseline` | refactor | `prepare_baseline_checkout()` delegates the copy and raises `BaselineUnavailable` when the report lists a missing artifact (same semantics as today) |
| `main_checkout_root()` | moves | from `baseline.py:34` into `native_artifacts`; `baseline.py` re-imports it so its own call site at `baseline.py:60` and the public name keep working |
| `.gitignore` | unchanged | `.so` stays ignored; synced files are untracked by design |

### Data Models

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py
class NativeGroup(BaseModel):
    """One family of native build artifacts declared in [tool.parrot.worktree]."""
    name: str
    copy: list[str]                       # globs, repo-relative, matched in the MAIN checkout
    pair_sources: list[str] = []          # globs whose each match needs a sibling compiled artifact
    required: bool = True                 # `copy` must match at least one file
    abi_scoped: bool = False              # presence counts only artifacts for the running EXT_SUFFIX
    autobuild: bool = False
    build: list[str] = []                 # argv; "{python}" is replaced with sys.executable
    build_cwd: str = "."                  # repo-relative
    build_timeout_s: int = 900
    manual_hint: str | None = None        # printed when a build is impossible or fails


class NativeManifest(BaseModel):
    """The parsed [tool.parrot.worktree] table."""
    enabled: bool = True
    groups: list[NativeGroup] = []


class MissingArtifact(BaseModel):
    """A declared artifact absent from the main checkout."""
    group: str
    reason: Literal["no_match", "unpaired_source", "abi_mismatch"]
    detail: str                           # the unmatched glob or the unpaired source path


class NativeSyncReport(BaseModel):
    """Outcome of one sync — never an exception carrier; callers decide severity."""
    enabled: bool
    copied: list[str] = []
    skipped: list[str] = []
    built: list[str] = []
    missing: list[MissingArtifact] = []
    warnings: list[str] = []
```

### New Public Interfaces

```python
def load_manifest(repo_root: Path) -> NativeManifest: ...
def missing_artifacts(main_root: Path, manifest: NativeManifest) -> list[MissingArtifact]: ...
def build_missing(main_root: Path, manifest: NativeManifest,
                  missing: Sequence[MissingArtifact]) -> tuple[list[str], list[str]]: ...
def sync_native_artifacts(*, main_root: Path, target: Path,
                          manifest: NativeManifest | None = None,
                          autobuild: bool = True) -> NativeSyncReport: ...
def main_checkout_root(worktree: Path) -> Path | None: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Declaration + manifest loader | yes | Models in §2; table shape in M1; `tomllib`; absent table ⇒ built-in defaults equal to the declared groups | — |
| M2: Copy engine | yes | `sync_native_artifacts()` signature; size+mtime skip; `copy2`; never raises | — |
| M3: Auto-build | yes | `fcntl.flock` on `<main_root>/.parrot/locks/native-<group>.lock`; re-check under lock; `subprocess.run(argv, cwd=…, timeout=…)`; `{python}` → `sys.executable`; failure ⇒ warning | — |
| M4: `ensure_worktree` wiring | yes | call sites + CLI flags + JSON key fixed below; stdout contract preserved | — |
| M5: `SubWorktreeManager` + `baseline.py` wiring | yes | `asyncio.to_thread`; log-not-raise for the pool; `BaselineUnavailable` kept for baseline | — |
| M6: Docs | yes | exact files and anchors listed | — |

### Module 1: Declaration + manifest loader
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py` (new)
  + `pyproject.toml`, `packages/navrules/Makefile`,
  `packages/navrules/rust/Cargo.lock` (modify)
- **Responsibility**: define the declaration format, add this repo's two
  groups to the root `pyproject.toml`, add the venv-safe navrules build
  target, and parse the table.
- **Depends on**: nothing in this spec.
- **Declared table** (added to the root `pyproject.toml`):
  ```toml
  [tool.parrot.worktree]
  # Native build artifacts a fresh `git worktree add` cannot carry, because every
  # one of them is gitignored. ensure_worktree / SubWorktreeManager copy these from
  # the main checkout into a new worktree before any agent runs in it (FEAT-722).
  enabled = true

  [[tool.parrot.worktree.native_group]]
  name = "cython-core"
  copy = ["packages/ai-parrot/src/parrot/**/*.so"]
  pair_sources = ["packages/ai-parrot/src/parrot/**/*.pyx"]
  abi_scoped = true
  autobuild = true
  build = ["{python}", "setup.py", "build_ext", "--inplace"]
  build_cwd = "packages/ai-parrot"
  build_timeout_s = 900
  manual_hint = "cd packages/ai-parrot && python setup.py build_ext --inplace"

  [[tool.parrot.worktree.native_group]]
  name = "navrules-pyo3"
  copy = ["packages/navrules/src/navrules/_native/*.so"]
  required = true
  abi_scoped = false        # abi3-py311: one .so covers CPython 3.11-3.13
  autobuild = true
  # `build-rust-wheel`, NOT the Makefile's `build-rust` (= `maturin develop`,
  # which reinstalls navrules into the SHARED venv — never in an automated path).
  build = ["make", "-C", "packages/navrules", "build-rust-wheel"]
  build_timeout_s = 900
  manual_hint = "make -C packages/navrules build-rust-wheel"
  ```
- **New Makefile target** (`packages/navrules/Makefile`, added next to
  `build-rust:` at line 8). Verified command sequence — the task blueprint
  writes the recipe, this is its contract:
  ```make
  # Build the Rust extension as a wheel and unpack ONLY its .so into src/,
  # without installing anything into the active environment (FEAT-722).
  # `--locked` guarantees an automated build never rewrites rust/Cargo.lock.
  build-rust-wheel:
  <TAB>uv run --no-sync --with maturin maturin build --release --locked --out <tmpdir>
  <TAB># then: unpack the wheel's `navrules/_native/*.so` into `src/`, rm the tmpdir
  ```
  `.PHONY` gains `build-rust-wheel`.
- **Lockfile refresh**: `packages/navrules/rust/Cargo.lock` still pins
  `navrules_native 1.2.3` while `rust/Cargo.toml:3` says `1.2.4`, so a
  `--locked` build fails today. M1 commits that one-line refresh
  (`1.2.3` → `1.2.4`) on the feature branch; without it the navrules
  auto-build would always degrade to its warning.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py  (new)
  """Native build artifacts a gitignored-by-design worktree cannot carry (FEAT-722)."""

  LOCK_DIRNAME: str = ".parrot/locks"
  SYNC_ENV_VAR: str = "PARROT_WORKTREE_SYNC_NATIVE"      # "0" disables the whole sync
  AUTOBUILD_ENV_VAR: str = "PARROT_WORKTREE_AUTOBUILD"    # "0" disables only building

  class NativeGroup(BaseModel):
      """One family of native build artifacts (see spec §2 Data Models)."""

  class NativeManifest(BaseModel):
      """The parsed ``[tool.parrot.worktree]`` table."""

  def load_manifest(repo_root: Path) -> NativeManifest:
      """Parse ``[tool.parrot.worktree]`` from ``repo_root/pyproject.toml``.

      Returns the built-in default manifest when the file or the table is
      absent; raises ValueError when the table is present but malformed —
      a typo in the declaration must be loud, not silently defaulted.
      """
  ```

### Module 2: Copy engine
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py`
- **Responsibility**: resolve globs in the main checkout, detect missing
  artifacts, copy into the target tree idempotently, and report.
- **Depends on**: Module 1.
- **Interface Skeleton**:
  ```python
  def main_checkout_root(worktree: Path) -> Path | None:
      """Root of the primary checkout that owns ``worktree``'s git common dir.

      Moved verbatim from test_scope/baseline.py:34 (FEAT-722); that module
      now imports it from here.
      """

  def missing_artifacts(main_root: Path, manifest: NativeManifest) -> list[MissingArtifact]:
      """Declared artifacts absent from ``main_root``.

      Three reasons: ``no_match`` (a ``required`` group's ``copy`` globs match
      nothing), ``unpaired_source`` (a ``pair_sources`` match has no sibling
      ``<stem>.*.so``/``<stem>.so``), ``abi_mismatch`` (``abi_scoped`` group
      whose only artifacts carry a foreign ``EXT_SUFFIX``).
      """

  def sync_native_artifacts(*, main_root: Path, target: Path,
                            manifest: NativeManifest | None = None,
                            autobuild: bool = True) -> NativeSyncReport:
      """Copy every declared native artifact from ``main_root`` into ``target``.

      Idempotent: a destination whose size and mtime already match the source
      is reported in ``skipped``, not re-copied, so this is safe on worktree
      reuse. Honours ``enabled``/``PARROT_WORKTREE_SYNC_NATIVE=0`` (returns an
      ``enabled=False`` report, copying nothing) and delegates to
      ``build_missing`` when ``autobuild`` and the group allow it. NEVER
      raises for a missing or unbuildable artifact: it records a
      ``MissingArtifact`` plus a ``manual_hint`` warning and returns.
      """
  ```

### Module 3: Auto-build under a cross-process lock
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py`
- **Responsibility**: build a missing artifact in the main checkout, at most
  once across concurrent worktree creations, for the running interpreter only.
- **Depends on**: Modules 1, 2.
- **Interface Skeleton**:
  ```python
  def build_missing(main_root: Path, manifest: NativeManifest,
                    missing: Sequence[MissingArtifact]) -> tuple[list[str], list[str]]:
      """Build the groups behind ``missing``; return ``(built_groups, warnings)``.

      For each distinct ``autobuild`` group: take an exclusive ``fcntl.flock``
      on ``<main_root>/.parrot/locks/native-<group>.lock`` (so N parallel
      ensure_worktree/pool runs produce ONE build), re-check
      ``missing_artifacts`` under the lock and skip when another process won
      the race, then run ``group.build`` (with ``{python}`` substituted by
      ``sys.executable``) in ``main_root / group.build_cwd`` with
      ``build_timeout_s``. A non-zero exit, timeout, missing ``fcntl``, or a
      group with ``autobuild=False`` yields a warning quoting
      ``group.manual_hint`` — never an exception.
      """
  ```

### Module 4: `ensure_worktree` wiring
- **Path**: `scripts/sdd/ensure_worktree.py` (modify)
- **Responsibility**: sync every worktree the CLI hands back, created or
  reused, and surface the report.
- **Depends on**: Modules 1-3.
- **Decision — the sync lives in `main()`, not in `ensure()`**: `ensure()`
  returns `tuple[Path, bool]` and is called directly by 14 assertions in
  `tests/sdd_scripts/test_ensure_worktree.py`. Calling the helper once in
  `main()`, after `ensure()` returns, covers the create and the reuse branch
  with a single call site, keeps that published contract (and those tests)
  unchanged, and puts the report exactly where its only consumer —
  `--json` / stderr — already lives.
- **Interface Skeleton**:
  ```python
  # scripts/sdd/ensure_worktree.py  (modifies scripts/sdd/ensure_worktree.py:344)
  #   path, created = ensure(...)            # signature UNCHANGED
  #   if not args.dry_run and not args.no_native_sync:
  #       report = sync_native_artifacts(
  #           main_root=repo_root, target=path,
  #           autobuild=not args.no_autobuild,
  #       )
  #   for warning in report.warnings:
  #       sys.stderr.write(f"warning: {warning}\n")   # NEVER stdout

  # CLI additions (modifies scripts/sdd/ensure_worktree.py:293)
  #   --no-native-sync   skip the copy entirely
  #   --no-autobuild     copy what exists, never build
  # --json output gains:  "native": {"enabled": bool, "copied": [...],
  #                                  "skipped": [...], "built": [...],
  #                                  "missing": [...], "warnings": [...]}
  # Bare stdout stays EXACTLY the worktree path; warnings go to stderr.
  # Exit code stays 0 when only the native sync had problems.
  ```

### Module 5: Pool sub-worktrees + baseline refactor
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py` (modify)
- **Responsibility**: every `sdd-coder` attempt worktree gets the artifacts;
  `baseline.py` stops carrying its own copy loop.
- **Depends on**: Modules 1-3.
- **Interface Skeleton**:
  ```python
  # worktree_manager.py  (modifies packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py:173)
  #   after `self._created[worker_id] = (path, branch)`:
  #   report = await asyncio.to_thread(sync_native_artifacts, main_root=…, target=Path(path))
  #   -> self.logger.warning(...) for each report.warnings entry; NEVER raise.

  # test_scope/baseline.py  (modifies packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py:62)
  #   replaces the `for so_file in main_root.glob("packages/*/src/**/*.so")` loop and
  #   the following `.pyx` pairing check with:
  #     report = sync_native_artifacts(main_root=main_root, target=target, autobuild=False)
  #     if report.missing:
  #         raise BaselineUnavailable(f"no compiled extension for … in main checkout")
  #   `main_checkout_root` is re-exported from native_artifacts (name kept).
  ```

### Module 6: Agent-facing documentation
- **Path**: `.claude/rules/worktree-management.md`,
  `.agent/skills/worktree-management/SKILL.md`, `.claude/agents/sdd-worker.md` (modify)
- **Responsibility**: retire the "known worktree limitation" folklore — state
  that the artifacts are synced (and built, when missing) automatically, name
  the declaration, and give the two manual build commands for the case where
  an automated build is refused or fails.
- **Depends on**: Modules 1-5 (document the landed behaviour).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_load_manifest_reads_declared_groups` | M1 | Root `pyproject.toml` yields both groups with the declared fields |
| `test_load_manifest_defaults_when_table_absent` | M1 | A `pyproject.toml` with no `[tool.parrot.worktree]` returns the built-in defaults |
| `test_load_manifest_rejects_malformed_table` | M1 | Unknown/ill-typed key raises `ValueError` (loud, not defaulted) |
| `test_both_declared_groups_are_autobuildable` | M1 | `cython-core` and `navrules-pyo3` both have `autobuild=True` and a non-empty `build` argv |
| `test_navrules_build_never_uses_maturin_develop` | M1 | The declared argv targets `build-rust-wheel`, and that Makefile recipe contains `maturin build` + `--locked` and **not** `maturin develop` |
| `test_navrules_cargo_lock_matches_crate_version` | M1 | `rust/Cargo.lock`'s `navrules_native` pin equals `rust/Cargo.toml`'s version — the precondition for a `--locked` build |
| `test_sync_copies_declared_artifacts` | M2 | Fake main root + empty target: every match lands at the same repo-relative path |
| `test_sync_is_idempotent` | M2 | Second run reports `skipped`, copies nothing, leaves mtime untouched |
| `test_sync_disabled_by_env` | M2 | `PARROT_WORKTREE_SYNC_NATIVE=0` ⇒ `enabled=False`, nothing copied |
| `test_missing_unpaired_source_detected` | M2 | A `.pyx` with no sibling `.so` ⇒ `reason="unpaired_source"` |
| `test_missing_abi_mismatch_detected` | M2 | Only a foreign-`EXT_SUFFIX` `.so` present ⇒ `reason="abi_mismatch"` |
| `test_autobuild_runs_declared_argv` | M3 | Stub group whose `build` argv creates the artifact ⇒ `built` non-empty, artifact copied |
| `test_autobuild_failure_is_a_warning` | M3 | Failing argv ⇒ no exception, `missing` kept, warning quotes `manual_hint` |
| `test_autobuild_skipped_when_disabled` | M3 | `autobuild=False` / `PARROT_WORKTREE_AUTOBUILD=0` ⇒ no subprocess, warning only |
| `test_autobuild_lock_serializes_builds` | M3 | Two concurrent calls on one group ⇒ argv runs once (counter file) |
| `test_main_syncs_on_create_and_reuse` | M4 | `tmp_git_repo`: artifact present after create, and re-synced on reuse after the fake main checkout "rebuilds" it |
| `test_main_stdout_is_only_the_path` | M4 | Bare CLI stdout is exactly the path even when warnings are emitted |
| `test_main_json_carries_native_report` | M4 | `--json` output has a `native` object with the documented keys |
| `test_main_no_native_sync_flag` | M4 | `--no-native-sync` copies nothing, still returns the worktree, exit 0 |
| `test_main_dry_run_skips_sync` | M4 | `--dry-run` performs no copy and no build |
| `test_ensure_signature_unchanged` | M4 | `ensure()` still returns a 2-tuple — the existing 14 call sites keep passing unmodified |
| `test_subworktree_create_syncs_artifacts` | M5 | `SubWorktreeManager.create()` leaves the artifact inside the sub-worktree |
| `test_subworktree_sync_failure_does_not_raise` | M5 | A sync that reports warnings logs and still returns the path |

### Integration Tests

| Test | Description |
|---|---|
| `test_worktree_can_import_parrot_utils` | Create a worktree through the `ensure_worktree` CLI in a hermetic clone, then `PYTHONPATH=packages/ai-parrot/src python -c "import parrot.utils"` inside it exits 0 — the §1 reproduction, inverted |
| `test_baseline_checkout_still_refuses_unbuilt_extension` | `prepare_baseline_checkout()` on a main root with an unpaired `.pyx` still raises `BaselineUnavailable` after the refactor |

### Validation Contract

tests:
- packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py
- packages/ai-parrot/tests/flows/dev_loop/test_worktree_manager.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py
- tests/sdd_scripts/test_ensure_worktree.py
- tests/sdd_scripts/test_brief_scaffold_integration.py
markers: none

### Test Data / Fixtures

```python
# Reuse the established idioms rather than inventing fixtures:
#   `tmp_git_repo`  — tests/sdd_scripts/test_ensure_worktree.py:19  (bare origin + dev clone
#                     carrying the SDD artifacts; the fixture M4's tests extend)
#   `git_sandbox`   — packages/ai-parrot/tests/flows/dev_loop/test_worktree_manager.py:34
#   `hermetic_repo` — packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py:27

@pytest.fixture
def fake_main_root(tmp_path: Path) -> Path:
    """A main checkout holding one .pyx + its sibling .so for the running EXT_SUFFIX."""

@pytest.fixture
def stub_manifest() -> NativeManifest:
    """One autobuildable group whose `build` argv just touches the artifact."""
```

---

## 5. Acceptance Criteria

- [ ] `[tool.parrot.worktree]` exists in the root `pyproject.toml` and declares
      the `cython-core` and `navrules-pyo3` groups exactly as in §3 M1.
- [ ] A worktree created by `python -m scripts.sdd.ensure_worktree …` contains
      `packages/ai-parrot/src/parrot/utils/types.<EXT_SUFFIX>` and
      `packages/ai-parrot/src/parrot/utils/parsers/toml.<EXT_SUFFIX>`.
- [ ] Inside that worktree, `PYTHONPATH=packages/ai-parrot/src python -c "import
      parrot.utils"` exits 0 (the §1 Problem Statement reproduction no longer
      reproduces).
- [ ] A per-attempt `sdd-coder` sub-worktree created by
      `SubWorktreeManager.create()` contains the same artifacts.
- [ ] Re-running `ensure_worktree` on an existing worktree re-syncs an artifact
      rebuilt in the main checkout, and reports untouched files as `skipped`.
- [ ] With the `cython-core` artifact deleted from the main checkout,
      `ensure_worktree` rebuilds it automatically and the worktree ends up with
      it; two concurrent runs build it exactly once.
- [ ] With `packages/navrules/src/navrules/_native/_navrules.abi3.so` deleted,
      `make -C packages/navrules build-rust-wheel` restores it, and afterwards
      `git status --porcelain packages/navrules/` is empty (no `Cargo.lock`
      churn) and nothing under `.venv/lib/python3.*/site-packages/navrules*`
      changed — the auto-build mutates neither tracked files nor the shared
      environment.
- [ ] No automated path invokes `maturin develop`
      (`grep -rn "maturin develop" pyproject.toml packages/ai-parrot/src/parrot/flows/dev_loop/ scripts/`
      returns nothing).
- [ ] A failing or impossible build never fails worktree creation: the command
      still prints the path, exits 0, and emits a stderr warning containing the
      group's `manual_hint`.
- [ ] `PARROT_WORKTREE_SYNC_NATIVE=0`, `PARROT_WORKTREE_AUTOBUILD=0`,
      `--no-native-sync` and `--no-autobuild` each behave as documented.
- [ ] Bare `ensure_worktree` stdout is still exactly the worktree path
      (`WORKTREE_PATH=$(…)` in `.claude/agents/sdd-worker.md:251` keeps working),
      and the exit code stays 0 when only the native sync reported problems.
- [ ] `ensure()` still returns `tuple[Path, bool]`: every pre-existing
      assertion in `tests/sdd_scripts/test_ensure_worktree.py` passes with no
      edit to its 14 `ensure(...)` call sites.
- [ ] `baseline.py` no longer contains its own `.so` glob loop and
      `test_scope/test_baseline.py` still passes unchanged.
- [ ] No synced artifact ever appears in `git status` inside a worktree.
- [ ] The Validation Contract tests pass; `ruff check` and `black --check` are
      clean on every touched file.
- [ ] `.claude/rules/worktree-management.md`, its `.agent` twin, and
      `.claude/agents/sdd-worker.md` describe the sync and drop the "known
      worktree limitation" framing.

---

## 6. Codebase Contract

### Verified Imports

```python
from scripts.sdd.sdd_meta import WorktreePlan, plan_worktree, resolve_flow  # verified: scripts/sdd/ensure_worktree.py:21
from scripts.sdd.brief_meta import brief_worktree_plan                      # verified: scripts/sdd/ensure_worktree.py:20
from parrot.flows.dev_loop.procs import git_env, run_bounded                # verified: packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py:34
from .datatypes import BaselineVerdict                                      # verified: packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py:18
from pydantic import BaseModel, Field                                       # verified: packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py:32
import tomllib                                                             # stdlib on requires-python >=3.11 (pyproject.toml:11)
```

### Existing Class Signatures

```python
# scripts/sdd/ensure_worktree.py
class EnsureWorktreeError(RuntimeError): ...                                  # line 26
def ensure(plan: WorktreePlan, *, repo_root: Path, sync: bool = True,
           require_paths: Sequence[str] = (), dry_run: bool = False,
           ) -> tuple[Path, bool]:                                            # line 49
def _create_worktree(plan: WorktreePlan, target_path: Path, *, repo_root: Path) -> None:   # line 195
def _find_reusable_worktree(plan, target_path, *, repo_root: Path) -> Path | None:         # line 165
def _missing_paths(root: Path, require_paths: Sequence[str]) -> list[str]:     # line 184
def main(argv: Sequence[str] | None = None) -> int:                           # line 265

# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py
GIT_TIMEOUT_S: float = 300.0                                                  # line 37
class SubWorktreeManager:                                                     # line 80
    def __init__(self, *, base_worktree: str, feature_branch: str, worktree_base_path: str) -> None:  # line 81
    self.base_worktree: str   # resolved absolute path of the feature worktree  # line 98
    self.logger = logging.getLogger(__name__)                                 # line 105
    async def _git(self, *args: str, cwd: str) -> Tuple[int, str, str]:       # line 117
    async def create(self, worker_id: str, *, base: Optional[str] = None) -> str:  # line 145

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py
class BaselineUnavailable(RuntimeError): ...                                  # line 25
def main_checkout_root(worktree: Path) -> Path | None:                        # line 34
def prepare_baseline_checkout(*, worktree: Path, base_ref: str, scratch: Path) -> Path:  # line 45

# packages/navrules/Makefile — the EXISTING rust target (NOT used by the auto-build)
build-rust:                                      # line 8
    uv run --with maturin maturin develop --release   # line 9 — reinstalls into the shared venv
# Verified 2026-10-22: `uv run --no-sync --with maturin maturin build --release
#   --out <tmp>` exits 0 in 13.7 s (warm target) and produces
#   navrules-1.2.4-cp311-abi3-manylinux_2_34_x86_64.whl whose only .so member is
#   `navrules/_native/_navrules.abi3.so`. It left navrules.pth, the venv's
#   navrules dist-info and the in-tree .so (mtime 2026-10-16) untouched, but DID
#   rewrite rust/Cargo.lock (stale 1.2.3 vs Cargo.toml 1.2.4) — hence `--locked`.

# packages/ai-parrot/setup.py — the cython-core build target
Extension(name='parrot.utils.types',        sources=['src/parrot/utils/types.pyx'])        # setup.py:14
Extension(name='parrot.utils.parsers.toml', sources=['src/parrot/utils/parsers/toml.pyx']) # setup.py:20
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `sync_native_artifacts()` | `main()` | one call right after `path, created = ensure(` — covers created and reused worktrees alike | `scripts/sdd/ensure_worktree.py:344` |
| `sync_native_artifacts()` | `SubWorktreeManager.create()` | `await asyncio.to_thread(...)` after the `_created` bookkeeping | `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py:173` |
| `sync_native_artifacts()` | `prepare_baseline_checkout()` | replaces the in-place glob loop | `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py:62-71` |
| `NativeSyncReport` | `ensure_worktree --json` | new `"native"` key next to `"created"` | `scripts/sdd/ensure_worktree.py:364` |
| `load_manifest()` | root `pyproject.toml` | `tomllib.load` of `[tool.parrot.worktree]` | new table — the file is 305 lines and holds no `[tool.parrot*]` today |

### Does NOT Exist (Anti-Hallucination)

- ~~`[tool.parrot]` / `[tool.parrot.worktree]` in any `pyproject.toml`~~ — this
  feature introduces the first one (`grep -rn '^\[tool\.parrot' --include=pyproject.toml` ⇒ no hits).
- ~~`parrot.flows.dev_loop.native_artifacts`~~ — new module, nothing imports it yet.
- ~~a shared worktree-artifact helper~~ — only `baseline.py:60-71` copies `.so`,
  inline; no other call site exists.
- ~~`yaml_rs`~~ — declared at `packages/ai-parrot/src/parrot/yaml-rs/Cargo.toml`
  but never built or installed: `import yaml_rs` ⇒ `ModuleNotFoundError`.
- ~~a `parrot_codec` artifact inside `packages/*/src/`~~ — it lives only in
  `.venv/lib/python3.12/site-packages/parrot_codec/` (a real wheel) and in
  `packages/ai-parrot/src/parrot/codec-rs/target/release/`, which is a cargo
  output directory, not an importable location.
- ~~a pure-Python fallback for `parrot.utils.types`~~ — `types.pyx` + the
  compiled `.so` are the only implementations (`parrot/utils/toml.py` is a
  different module from `parrot/utils/parsers/toml.pyx`).
- Tests for `scripts/sdd/ensure_worktree.py` **do** exist — at
  `tests/sdd_scripts/test_ensure_worktree.py` (repo-root `tests/` tree, not
  under `packages/`; 323 lines, `tmp_git_repo` fixture at line 19, 14 direct
  `ensure(...)` call sites that unpack a 2-tuple, plus `main()` coverage).
  `tests/sdd_scripts/test_brief_scaffold_integration.py:13` imports `main` as
  well. This is why M4 does NOT change `ensure()`'s arity.
- ~~`filelock` usage in `parrot/`~~ — the package is installed (4.2.0) but the
  repo's cross-process locking idiom is a guarded `import fcntl`
  (`test_scope/green_cache.py:24-27`, `sdd_coder/evidence.py:48`). Follow that.

### Edit Sites (Blueprint Anchors)

Verified against: `add1f89ea`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py` | CREATE | — | — | — |
| `pyproject.toml` | MODIFY | `[tool.pylint.messages_control]` | `pyproject.toml:299` | 1 |
| `packages/navrules/Makefile` | MODIFY | `build-rust:` | `Makefile:8` | 1 |
| `packages/navrules/rust/Cargo.lock` | MODIFY | `version = "1.2.3"` in the `name = "navrules_native"` block | `Cargo.lock:71` | 1 (within that block) |
| `scripts/sdd/ensure_worktree.py` | MODIFY | `    parser.add_argument("--json", action="store_true", help="Output JSON instead of bare path.")` | `ensure_worktree.py:293` | 1 |
| `scripts/sdd/ensure_worktree.py` | MODIFY | `        path, created = ensure(` | `ensure_worktree.py:344` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py` | MODIFY | `        self._created[worker_id] = (path, branch)` | `worktree_manager.py:173` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py` | MODIFY | `            for so_file in main_root.glob("packages/*/src/**/*.so"):` | `baseline.py:62` | 1 |
| `tests/sdd_scripts/test_ensure_worktree.py` | MODIFY | `def tmp_git_repo(tmp_path: Path) -> Path:` | `test_ensure_worktree.py:19` | 1 |
| `.claude/rules/worktree-management.md` | MODIFY | the bullet opening "The shared .venv is editable-installed against the **main checkout**" | `worktree-management.md:52` | 1 |
| `.agent/skills/worktree-management/SKILL.md` | MODIFY | same bullet as above | `SKILL.md:50` | 1 |
| `.claude/agents/sdd-worker.md` | MODIFY | `WORKTREE_PATH=$(python -m scripts.sdd.ensure_worktree \` | `sdd-worker.md:251` | 1 |

> `ensure()` keeps its `tuple[Path, bool]` return. Verified callers
> (`grep -rn "ensure_worktree import\|ensure_worktree\.ensure(" --include=*.py .`,
> excluding `.venv/`, `worktrees/`, `build/`): `tests/sdd_scripts/test_ensure_worktree.py:11`
> and `tests/sdd_scripts/test_brief_scaffold_integration.py:13`. Everything
> else goes through the CLI. `/sdd-task` must re-run that grep before writing
> M4's task.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Pydantic v2 models for the manifest and report (`.claude/rules/codebase-conventions.md`);
  `logging.getLogger(__name__)`, never `print`, inside the package module. The
  `ensure_worktree` CLI keeps its existing `sys.stderr.write` style for
  operator-facing warnings.
- Cross-process locking: guarded `import fcntl` with an `ImportError` fallback
  that degrades to "cannot build here", mirroring
  `test_scope/green_cache.py:24-27`.
- No shell: `subprocess.run(argv, cwd=…, timeout=…, check=False)` with an argv
  list, `{python}` → `sys.executable`. Never `shell=True`.
- `native_artifacts.py` imports nothing from the rest of `parrot` (only stdlib
  + pydantic), so `test_scope.baseline`, `worktree_manager` and
  `scripts.sdd.ensure_worktree` can all import it without a cycle.
- `shutil.copy2` to preserve mtime, which is what makes the skip check cheap
  and the "rebuilt in main, re-sync on reuse" behaviour correct.

### Known Risks / Gotchas

- **Why the sync sits in `main()`.** `ensure()` is a published two-value
  contract with 14 direct test call sites; threading a report through it would
  churn the one test file that protects worktree provisioning. `main()` runs
  after both the create and the reuse branch, so one call site there covers
  everything the CLI hands back. The cost is explicit: a Python caller that
  imports `ensure()` directly gets no sync — only the tests do that today.
- **The stdout contract.** `sdd-worker` captures `WORKTREE_PATH=$(python -m
  scripts.sdd.ensure_worktree …)`. One stray `print` of a warning corrupts the
  path for every agent. Warnings go to stderr; the JSON mode carries them
  structurally. Covered by `test_ensure_stdout_is_only_the_path`.
- **Auto-building mutates the main checkout.** `setup.py build_ext --inplace`
  writes `packages/ai-parrot/build/` and in-tree `.so`/`.cpp` files — all
  gitignored, so `git status` stays clean, but a build racing a parallel
  session's build would be real damage. Hence the `fcntl.flock` + re-check
  under the lock, and the `build_timeout_s` cap.
- **`maturin develop` must never appear in an automated path.** It installs
  into the shared `.venv`, which `.claude/rules/worktree-management.md` §4
  forbids and which has already broken sessions twice (project memory: *stale
  editable .pth from removed worktree*, *shared venv clobbered by concurrent
  sessions*). The navrules auto-build therefore goes through
  `build-rust-wheel` (`maturin build --out` + unpack), proven venv-neutral on
  2026-10-22; the existing `build-rust` target stays for humans and is never
  called by this feature.
- **An auto-build must not dirty a tracked file.** The measured `maturin build`
  run rewrote `packages/navrules/rust/Cargo.lock` (its `navrules_native` pin is
  stale: `1.2.3` vs `Cargo.toml`'s `1.2.4`). A worktree-creation step that
  silently edits a tracked file would leak into whatever commit comes next, so
  the declared build passes `--locked`, which fails loudly (→ warning + manual
  hint) instead of editing the lock. M1 refreshes that one line so `--locked`
  succeeds; any future staleness degrades to a warning, never a silent edit.
- **Cold cargo builds are slow.** 13.7 s was a warm `rust/target`; a cold
  release build with `lto = true, codegen-units = 1` takes minutes — hence
  `build_timeout_s = 900`, with the group lock held for the whole build.
- **ABI tags.** The main checkout currently holds both `cpython-311` and
  `cpython-312` artifacts. Presence checks are scoped to the running
  interpreter's `sysconfig.get_config_var("EXT_SUFFIX")`; the copy is not —
  copying the extra file costs ~500 KB and helps a session on the other
  interpreter.
- **Sub-worktree volume.** The `sdd-coder` pool creates one sub-worktree per
  attempt; at ~2 MB of artifacts per tree this is negligible, but the sync must
  stay silent-and-fast on the hot path (skip-by-mtime, no build unless missing).
- **Untracked by design.** The synced files are gitignored, so they never enter
  a commit; `git worktree remove` deletes them with the tree. A future
  `--force`-less `git worktree remove` will not complain about them because
  ignored files do not block removal.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | None. `tomllib`, `fcntl`, `shutil`, `subprocess`, `sysconfig` are stdlib; `pydantic` is already a core dependency. |

---

## 8. Open Questions

- [x] What should happen when a declared artifact is missing from the main
      checkout? — *Resolved by the user, 2026-10-22*: build it automatically,
      then copy — concurrency-safe, running interpreter only, opt-outable, and
      degrading to a warning with the manual command if the build fails.
- [x] Where should the artifact list live? — *Resolved by the user,
      2026-10-22*: declared in `pyproject.toml` (shared libraries + crates),
      read by the tooling before the worktree starts being used.
- [x] Should `navrules-pyo3` ever be auto-built? — *Resolved by the user,
      2026-10-22 (spec rev 0.2)*: **yes**, via a venv-free build. The
      `maturin build --release --locked --out <tmp>` + unpack path was measured
      before being written into this spec (13.7 s, exit 0, venv and in-tree
      `.so` untouched), so the group is `autobuild = true` against the new
      `build-rust-wheel` target. `maturin develop` remains banned from every
      automated path.
- [ ] Should `/sdd-done`'s cleanup or `remove_worktree.py` prune synced
      artifacts explicitly? Assumed unnecessary (ignored files die with the
      tree). — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `n/a` · Status: skipped (no exploration
> document — this spec was written directly from the user's request, so §3b's
> precondition "an accepted brainstorm/proposal exists" was never met; intake
> mode did not run either)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-722
  (`.claude/worktrees/feat-FEAT-722-worktree-native-artifact-sync`, base
  `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree
  inside it.
- **Module dependency graph**:
  - M2 → M1 (M2's `missing_artifacts`/`sync_native_artifacts` consume
    `NativeManifest` from M1)
  - M3 → M1, M2 (`build_missing` re-checks via M2's `missing_artifacts`)
  - M4 → M2, M3 (`main()` calls `sync_native_artifacts` with `autobuild`)
  - M5 → M2, M3 (same entry point, two other callers)
  - M6 → M4, M5 (documents landed behaviour)
  - M4 and M5 have no edge between them and are expected to run concurrently.
- **Shared files**: `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py`
  is written by M1, M2 and M3 — their tasks are serialized.
  `packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py` likewise.
- **Exclusive resources**: any task whose validation deletes and rebuilds a
  main-checkout `.so` mutates shared state outside its own files → those tasks
  are `parallel: false`. M3's lock test must use a stub group with a temporary
  main root, never the real `cython-core` group.
- **Cross-feature dependencies**: none. This feature only adds a step to
  worktree creation; no other open spec touches `ensure_worktree.py`,
  `worktree_manager.py` or `baseline.py`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-22 | Jesus Lara | Initial draft — FEAT-722 |
| 0.2 | 2026-10-22 | Jesus Lara | §8 Q1 resolved: navrules IS auto-built via a new venv-free `build-rust-wheel` target (`maturin build --locked --out` + unpack, measured 13.7 s); `--locked` added so an auto-build cannot rewrite `rust/Cargo.lock`; M1 refreshes the stale lock pin |
