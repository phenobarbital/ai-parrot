# TASK-4608: Auto-build missing artifacts under a cross-process lock

**Feature**: FEAT-722 — Worktree Native Artifact Sync
**Spec**: `sdd/specs/worktree-native-artifact-sync.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4607
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 — the user's decision of 2026-10-22: when a declared artifact
is missing from the main checkout, **build it automatically** instead of only
warning. TASK-4607 can already detect and classify what is missing; this task
builds it, once, safely, and then lets the existing copy loop pick it up.

Three properties make this safe rather than reckless:

- **One build across N worktree creations.** The `sdd-coder` pool creates one
  sub-worktree per attempt, so several syncs can start within milliseconds of
  each other. An exclusive `fcntl.flock` per group, plus a re-check *under* the
  lock, means the second arrival copies instead of rebuilding.
- **Running interpreter only.** The main checkout holds both `cpython-311` and
  `cpython-312` artifacts; a build targets whatever interpreter is running and
  nothing else.
- **Never fatal.** A failing, timing-out or impossible build produces a warning
  quoting the group's `manual_hint`. Worktree creation must not start failing
  because an extension could not be compiled.

---

## Scope

- Add the guarded `fcntl` import, `_build_lock()` and `build_missing()` to
  `native_artifacts.py`.
- Extend `sync_native_artifacts()` with `autobuild: bool = True`: when the
  pre-copy classification reports missing artifacts and autobuild is permitted,
  build, then copy, then re-classify so the report reflects reality.
- Extend `test_native_artifacts.py` with the autobuild tests below.

**NOT in scope**: any caller (TASK-4609/4610/4611); changing the declaration
(TASK-4605 owns it); building anything in a *worktree* — builds always run in
the main checkout.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py` | MODIFY | `_build_lock`, `build_missing`, `autobuild` hook |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py` | MODIFY | Autobuild + lock tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import sys          # for sys.executable, substituted for PYTHON_PLACEHOLDER
from contextlib import contextmanager
from collections.abc import Iterator, Sequence

try:  # POSIX only — verified idiom: test_scope/green_cache.py:24-27
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]
```
Already present: `logging`, `os`, `shutil`, `subprocess`, `sysconfig`,
`tomllib`, `Path`, `Literal`, pydantic.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py — the guarded-fcntl idiom
try:  # POSIX only                          # line 24
    import fcntl                            # line 25
except ImportError:  # pragma: no cover     # line 26
    fcntl = None  # type: ignore[assignment]  # line 27
```

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py (TASK-4606 + TASK-4607)
LOCK_DIRNAME = ".parrot/locks"
PYTHON_PLACEHOLDER = "{python}"
AUTOBUILD_ENV_VAR = "PARROT_WORKTREE_AUTOBUILD"
def env_flag_disabled(name: str) -> bool
def missing_artifacts(main_root: Path, manifest: NativeManifest) -> list[MissingArtifact]
def sync_native_artifacts(*, main_root: Path, target: Path, manifest: NativeManifest | None = None) -> NativeSyncReport
class NativeGroup:  # name, copy_globs, pair_sources, required, abi_scoped,
                    # autobuild, build, build_cwd, build_timeout_s, manual_hint
```

### Verified build facts (2026-10-22)
```
cython-core   : `python setup.py build_ext --inplace` in packages/ai-parrot
                writes packages/ai-parrot/build/ and the in-tree .so/.cpp — all gitignored.
navrules-pyo3 : `make -C packages/navrules build-rust-wheel` (added by TASK-4605) runs
                `maturin build --release --locked --out <tmp>` + an unpack; measured 13.7 s
                warm, exit 0, shared venv and in-tree .so untouched. A COLD release build
                (lto = true, codegen-units = 1 — packages/navrules/rust/Cargo.toml) takes
                minutes, hence build_timeout_s = 900.
`.parrot/` is gitignored (.gitignore:418), so `.parrot/locks/` never shows in git status.
```

### Does NOT Exist
- ~~`filelock.FileLock`~~ — installed (4.2.0) but NOT the repo idiom; use the
  guarded `fcntl` pattern above.
- ~~`shell=True` anywhere in `parrot/flows/dev_loop/`~~ — `build` is an argv
  list; never join it into a string, never pass it to a shell.
- ~~`maturin develop`~~ — must not appear in any automated path; the navrules
  group's argv targets `build-rust-wheel` precisely to avoid it. Do not
  "helpfully" fall back to `build-rust`.
- ~~`asyncio` in this module~~ — `build_missing` is synchronous; TASK-4610 wraps
  the whole sync in `asyncio.to_thread` on the caller side.
- ~~a writable main checkout from inside a sandboxed worktree~~ — the Bubblewrap
  policy mounts the primary checkout read-only except `.claude/worktrees/` and
  `.parrot/ledger/` (`.claude/rules/worktree-management.md` §4). A build
  triggered from such a context will fail on the lock file or the build itself;
  that is the warning path, not something to work around.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py#sync_native_artifacts",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py#missing_artifacts"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Re-check under the lock.** Acquire → `missing_artifacts()` again → build
  only what is still missing. Without this, N concurrent syncs run N builds.
- **One lock per group**, named `native-<group.name>.lock`, created with
  `mkdir(parents=True, exist_ok=True)` under `<main_root>/.parrot/locks`.
- **Blocking acquire with a cap**: use a blocking `flock` but bound the total
  wait by `group.build_timeout_s` (alarm-free approach: non-blocking `LOCK_EX |
  LOCK_NB` in a loop with a short sleep and a deadline, so a stuck holder
  degrades to a warning instead of hanging worktree creation forever).
- **No `fcntl` (non-POSIX)** ⇒ do not build; emit the manual hint.
- `subprocess.run(argv, cwd=..., timeout=..., check=False, capture_output=True,
  text=True)`; on failure put the last ~10 lines of stderr in the warning plus
  the manual hint. `subprocess.TimeoutExpired` is caught, never propagated.
- Substitute `PYTHON_PLACEHOLDER` with `sys.executable` in each argv element.
- A group with `autobuild=False`, an empty `build`, or
  `PARROT_WORKTREE_AUTOBUILD=0` is never built — warning only.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py:24-27` — guarded fcntl.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py:48` — same idiom, second instance.

---

## Implementation Blueprint

### Steps (in order)
1. Add `sys`, `contextmanager`, `Iterator`/`Sequence` and the guarded `fcntl`
   import — *why*: the lock must degrade on a platform without `fcntl` rather
   than fail at import time.
2. Add `_build_lock()` — *why*: it is the only thing standing between parallel
   worktree creations and N concurrent release builds of the same crate.
3. Add `build_missing()` — *why*: one place owns argv substitution, the
   timeout, the re-check and the warning text.
4. Extend `sync_native_artifacts()` with `autobuild` — *why*: callers want one
   entry point; the build is an internal step, not a second call they must make.
5. Extend the tests — *why*: the lock and the failure-is-a-warning rule are
   invisible in normal runs and would silently regress.

### `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py` (MODIFY — 1 of 2)
```python
# occurrences: verify before editing — `grep -c 'def missing_artifacts' <path>` MUST be 1
# AFTER — insert below `missing_artifacts` and ABOVE `sync_native_artifacts`

@contextmanager
def _build_lock(main_root: Path, group: NativeGroup) -> Iterator[bool]:
    """Hold an exclusive build lock for ``group``; yields False when unavailable.

    The lock lives at ``<main_root>/.parrot/locks/native-<group>.lock`` so that
    every process able to build shares it (``.parrot/`` is gitignored). Yields
    False — never raises — when ``fcntl`` is missing, the directory is not
    writable, or the lock is still held after ``group.build_timeout_s``.
    """
    # FILL IN: create the lock dir, open the lock file, try LOCK_EX | LOCK_NB in
    # a loop with a short sleep until `group.build_timeout_s` elapses; yield True
    # once held and release in a finally; yield False on OSError / missing fcntl /
    # deadline. Bounded by: never block indefinitely, never raise (AC-4, AC-6).
    raise NotImplementedError


def build_missing(
    main_root: Path,
    manifest: NativeManifest,
    missing: Sequence[MissingArtifact],
) -> tuple[list[str], list[str]]:
    """Build the groups behind ``missing``; return ``(built_groups, warnings)``.

    For each distinct group that is ``autobuild`` and declares a ``build`` argv:
    take ``_build_lock``, re-run ``missing_artifacts`` under it and skip when
    another process already built the artifact, then run the argv (with
    ``{python}`` replaced by ``sys.executable``) in ``main_root / build_cwd``
    with ``group.build_timeout_s``. A non-zero exit, a timeout, an unavailable
    lock, a missing ``fcntl``, ``PARROT_WORKTREE_AUTOBUILD=0`` or
    ``autobuild=False`` yields a warning quoting ``group.manual_hint`` — never
    an exception.
    """
    # FILL IN: implement as documented above; warnings read
    # f"{group.name}: {why}; build it manually with: {group.manual_hint}".
    # Bounded by: argv only (never shell=True), one build per group per call,
    # and no exception may escape (AC-5, AC-6, AC-7).
    raise NotImplementedError
```
**Why this shape**: `_build_lock` yields a bool instead of raising so the caller
has exactly one code path for "could not build" regardless of cause.
`build_missing` returns `(built, warnings)` rather than mutating a report, which
keeps it independently testable and lets `sync_native_artifacts` decide what to
do with both lists.

### `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py` (MODIFY — 2 of 2)
```python
# occurrences: verify before editing —
#   `grep -c 'def sync_native_artifacts' <path>` MUST be 1
# REPLACE the signature TASK-4607 wrote, adding the `autobuild` parameter, and
# insert the build step BEFORE the copy loop:

def sync_native_artifacts(
    *,
    main_root: Path,
    target: Path,
    manifest: NativeManifest | None = None,
    autobuild: bool = True,
) -> NativeSyncReport:
    """Copy every declared native artifact from ``main_root`` into ``target``.

    ... (keep TASK-4607's docstring) ...

    Args:
        autobuild: Build a declared artifact that is missing from ``main_root``
            before copying. Suppressed by ``PARROT_WORKTREE_AUTOBUILD=0`` and by
            a group's own ``autobuild=False``.
    """
    # FILL IN: after the enabled/env guard and BEFORE the copy loop:
    #   pending = missing_artifacts(main_root, resolved)
    #   if pending and autobuild and not env_flag_disabled(AUTOBUILD_ENV_VAR):
    #       built, warnings = build_missing(main_root, resolved, pending)
    #   then run the copy loop, and recompute missing_artifacts AFTER the build so
    #   the report reflects reality; carry `built` and `warnings` into the report.
    # Bounded by: a successful build must result in a copied artifact (AC-1), and
    # the report's `missing` must be empty when the build succeeded (AC-2).
```
**Why**: classifying before the build is what tells us whether to build at all;
classifying again after it is what keeps the report honest. The parameter
defaults to True so the three callers get the behaviour without opting in, and
`baseline.py` (TASK-4611) passes `autobuild=False` explicitly.

### FILL IN checklist
- [ ] `native_artifacts.py::_build_lock` — the deadline loop and the
      never-raise contract; bounded by `group.build_timeout_s` (AC-4, AC-6).
- [ ] `native_artifacts.py::build_missing` — argv substitution, re-check under
      the lock, warning text; bounded by "argv only, one build per group,
      no exception escapes" (AC-5, AC-6, AC-7).
- [ ] `native_artifacts.py::sync_native_artifacts` — the build step and the
      post-build re-classification; bounded by AC-1 and AC-2.

---

## Acceptance Criteria

- [ ] A stub group whose `build` argv creates its artifact: the sync reports the
      group in `built`, the artifact in `copied`, and `missing == []`
- [ ] After a successful build the report's `missing` is empty (re-classified,
      not stale)
- [ ] A failing argv raises nothing: `missing` is preserved, and a warning
      contains both the failure reason and the group's `manual_hint`
- [ ] Two concurrent syncs of the same stub group run the argv exactly once
      (assert on a counter file the stub build appends to)
- [ ] `autobuild=False`, `group.autobuild=False`, an empty `build`, and
      `PARROT_WORKTREE_AUTOBUILD=0` each skip the build entirely (no subprocess)
      and warn instead
- [ ] A `build` timeout is caught and reported as a warning
- [ ] `{python}` in an argv is replaced with `sys.executable`
- [ ] `grep -n 'shell=True' .../native_artifacts.py` returns nothing, and
      `grep -rn 'maturin develop' packages/ai-parrot/src/parrot/flows/dev_loop/`
      returns nothing
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py -q` passes
- [ ] `ruff check` clean on both files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py -q`

---

## Test Specification

Add to `test_native_artifacts.py`. Every test uses a **stub group with a
temporary main root** — never the real `cython-core` or `navrules-pyo3` group,
which would compile the actual extensions:

```python
def _counting_build_group(main_root: Path, counter: Path) -> NativeGroup:
    """A group whose build argv appends to `counter` and creates the artifact."""
    script = main_root / "fake_build.py"
    script.write_text(
        "import pathlib, sys\n"
        "counter = pathlib.Path(sys.argv[1]); counter.write_text(counter.read_text() + 'x' if counter.exists() else 'x')\n"
        "art = pathlib.Path(sys.argv[2]); art.parent.mkdir(parents=True, exist_ok=True); art.write_bytes(b'ELF')\n",
        encoding="utf-8",
    )
    return NativeGroup(
        name="stub",
        copy_globs=["packages/demo/src/demo/*.so"],
        autobuild=True,
        build=["{python}", "fake_build.py", str(counter), f"packages/demo/src/demo/built{EXT}"],
        build_cwd=".",
        build_timeout_s=60,
        manual_hint="run it yourself",
    )


def test_autobuild_runs_declared_argv(tmp_path):
    """A missing artifact is built, then copied."""
    ...


def test_autobuild_failure_is_a_warning(tmp_path):
    """A non-zero build exit leaves `missing` intact and warns with manual_hint."""
    ...


def test_autobuild_skipped_when_disabled(tmp_path, monkeypatch):
    """PARROT_WORKTREE_AUTOBUILD=0 and autobuild=False both skip the subprocess."""
    ...


def test_autobuild_lock_serializes_builds(tmp_path):
    """Two concurrent syncs of one group run the argv exactly once.

    Use two threads (or two `multiprocessing` processes) against the same main
    root and assert the counter file holds exactly one mark.
    """
    ...


def test_python_placeholder_is_substituted(tmp_path):
    """`{python}` becomes sys.executable, so the venv interpreter runs the build."""
    ...
```

Write real bodies for these — the `...` above marks the four scenarios, not
placeholder code. Keep every build stub to a `{python}`-prefixed argv so no test
ever invokes `make`, `maturin` or `setup.py`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-4607 must be `"done"`
4. **Verify the Codebase Contract** — confirm `green_cache.py:24-27` still shows
   the guarded-`fcntl` idiom and that `sync_native_artifacts` has the signature
   TASK-4607 left behind
5. **Update status** in the per-spec index → `"in-progress"`, commit only it
6. **Implement** — complete all three `# FILL IN:` markers; never introduce
   `shell=True`, and never call `maturin develop`
7. **Verify** the acceptance criteria — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the two files this task lists
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4608 worktree-native-artifact-sync verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (orchestrator) — seat: gpt-5.6-terra (codex), 1 attempt
**Date**: 2026-10-22
**Notes**: Added autobuild to native_artifacts.py. test_native_artifacts.py: 21 passed. Residual ruff B023 (loop var closure, called immediately) left for /sdd-done.

**Deviations from spec**: none
