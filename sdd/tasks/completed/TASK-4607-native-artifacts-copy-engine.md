# TASK-4607: Copy engine — main_checkout_root, missing_artifacts, sync_native_artifacts

**Feature**: FEAT-722 — Worktree Native Artifact Sync
**Spec**: `sdd/specs/worktree-native-artifact-sync.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4606
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. With the models and the loader in place (TASK-4606), this
task adds the three functions that actually move artifacts: locate the main
checkout that owns a worktree, decide which declared artifacts are missing, and
copy the ones that exist into a target tree — idempotently, so the same call is
safe on worktree *reuse* after a rebuild.

This is the function every caller in the feature uses:
`ensure_worktree.main()` (TASK-4609), `SubWorktreeManager.create()`
(TASK-4610) and `prepare_baseline_checkout()` (TASK-4611).

`main_checkout_root` is **copied** (not moved) from
`test_scope/baseline.py:34-42`: this task must not touch `baseline.py`, which
TASK-4611 edits to delete its now-duplicate copy and import this one instead.

---

## Scope

- Add `main_checkout_root()` to `native_artifacts.py`, behaviourally identical
  to `baseline.py:34-42`.
- Add `missing_artifacts()` returning one `MissingArtifact` per declared
  artifact absent from the main checkout, with the three documented reasons.
- Add `sync_native_artifacts(*, main_root, target, manifest=None)` — copy,
  skip-when-up-to-date, report. No building in this task.
- Extend `test_native_artifacts.py` with the copy/missing tests below.

**NOT in scope**: `build_missing`, the `fcntl` lock and the `autobuild`
parameter (TASK-4608 adds all three, including extending this function's
signature); editing `baseline.py` (TASK-4611); any caller wiring.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py` | MODIFY | Add the three functions |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py` | MODIFY | Add copy/missing tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# added to native_artifacts.py by THIS task (stdlib only — the module must not import parrot)
import logging
import shutil
import subprocess
import sysconfig
```
Already present from TASK-4606: `os`, `tomllib`, `Path`, `Literal`,
`BaseModel`, `ConfigDict`, `Field`.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py — the logic to REPLICATE
def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:   # line 28
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)

def main_checkout_root(worktree: Path) -> Path | None:                 # line 34
    """Root of the primary checkout that owns ``worktree``'s git common dir."""
    try:
        proc = _git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir")  # line 36
    except OSError:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.strip()).parent                            # line 41

# the glob + pairing rule this task generalises (baseline.py:62-71)
for so_file in main_root.glob("packages/*/src/**/*.so"):               # line 62
for pyx in target.glob("packages/*/src/**/*.pyx"):                     # line 69
    if not any(pyx.parent.glob(f"{stem}.*.so")) and not (pyx.parent / f"{stem}.so").exists():  # line 70
```

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py (TASK-4606)
NativeGroup(name, copy_globs, pair_sources, required, abi_scoped, autobuild, build, build_cwd, build_timeout_s, manual_hint)
NativeManifest(enabled: bool, groups: list[NativeGroup])
MissingArtifact(group: str, reason: Literal["no_match", "unpaired_source", "abi_mismatch"], detail: str)
NativeSyncReport(enabled: bool, copied, skipped, built, missing, warnings)
def load_manifest(repo_root: Path) -> NativeManifest
def env_flag_disabled(name: str) -> bool
SYNC_ENV_VAR = "PARROT_WORKTREE_SYNC_NATIVE"
```

### Verified environment facts (2026-10-22, main checkout)
```
sysconfig.get_config_var("EXT_SUFFIX") == ".cpython-312-x86_64-linux-gnu.so"   (venv is 3.12)
packages/ai-parrot/src/parrot/utils/types.cpython-311-x86_64-linux-gnu.so      present
packages/ai-parrot/src/parrot/utils/types.cpython-312-x86_64-linux-gnu.so      present
packages/ai-parrot/src/parrot/utils/parsers/toml.cpython-{311,312}-...so       present
packages/navrules/src/navrules/_native/_navrules.abi3.so                       present (2 441 408 bytes)
every .claude/worktrees/* tree                                                 holds ZERO .so files
```

### Does NOT Exist
- ~~`build_missing`~~ — TASK-4608 adds it. Do NOT call it, do NOT add an
  `autobuild` parameter, and do NOT leave a placeholder hook for it: this
  task's `sync_native_artifacts` simply reports what is missing.
- ~~`Path.glob` with a leading `/`~~ — `copy_globs` entries are repo-relative;
  resolve them as `main_root.glob(pattern)`, never `Path(pattern)`.
- ~~`shutil.copy`~~ — use `shutil.copy2`: it preserves mtime, which is exactly
  what makes the idempotence check cheap and the "rebuilt in main ⇒ re-sync on
  reuse" behaviour correct.
- ~~a `.pyd` artifact~~ — Windows extensions are out of scope; the declaration
  only lists `*.so` globs.
- ~~`baseline.main_checkout_root` as an import source~~ — do not import from
  `test_scope.baseline` (that would re-introduce the `parrot` import this
  module forbids, and invert the dependency TASK-4611 establishes).

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
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py#main_checkout_root"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Never raise for a missing artifact.** `sync_native_artifacts` returns a
  report; the caller decides whether that is fatal (`baseline.py` treats it as
  fatal, worktree creation does not).
- **Idempotence rule**: copy only when the destination is absent or its
  `(st_size, st_mtime_ns)` differs from the source's; otherwise append the path
  to `skipped`.
- **Never create directories outside the target tree**, and skip a match whose
  destination parent does not exist in the target *unless* the parent is inside
  the target tree — `baseline.py:63-65` simply skipped those; here, create the
  parent with `mkdir(parents=True, exist_ok=True)` because a worktree always
  carries the source tree, so the parent exists in every real case and this only
  matters for synthetic test trees.
- Paths in the report are **repo-relative POSIX strings**
  (`str(path.relative_to(main_root))`), never absolute — they are rendered into
  `--json` output and warnings.
- `logging.getLogger(__name__)` at module level; `logger.debug` for each copy,
  `logger.warning` never from this task (the caller surfaces warnings).

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py:56-76` —
  the loop this generalises, including the pairing check.
- `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:52-70` —
  how this repo locates checkout roots defensively.

---

## Implementation Blueprint

### Steps (in order)
1. Add the new stdlib imports and the module logger — *why*: all three
   functions need them and the module must stay parrot-free.
2. Add `_git` + `main_checkout_root` — *why*: callers hold a worktree path, not
   the main checkout, so every entry point starts by resolving it.
3. Add `_ext_suffix` + `missing_artifacts` — *why*: the build decision
   (TASK-4608) and the warnings both derive from this one classification.
4. Add `sync_native_artifacts` — *why*: the single entry point all three
   callers use.
5. Extend the tests — *why*: idempotence and the three `reason` values are the
   behaviours later tasks silently depend on.

### `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py` (MODIFY)
```python
# occurrences: verify before editing — `grep -c 'def load_manifest' <path>` MUST be 1
#   (the file is CREATEd by TASK-4606, so the count cannot be verified at /sdd-task time)
# AFTER — append below the end of `load_manifest`, keeping the module's import
#   block at the top (add `import logging, shutil, subprocess, sysconfig` there)

logger = logging.getLogger(__name__)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git in ``cwd`` capturing text output; never raises on a non-zero exit."""
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)


def main_checkout_root(worktree: Path) -> Path | None:
    """Root of the primary checkout that owns ``worktree``'s git common dir.

    Replicates ``test_scope.baseline.main_checkout_root`` (baseline.py:34);
    TASK-4611 deletes that copy and imports this one.
    """
    try:
        proc = _git(Path(worktree), "rev-parse", "--path-format=absolute", "--git-common-dir")
    except OSError:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.strip()).parent


def _ext_suffix() -> str:
    """The running interpreter's extension suffix, e.g. ``.cpython-312-x86_64-linux-gnu.so``."""
    return sysconfig.get_config_var("EXT_SUFFIX") or ".so"


def _matches(root: Path, patterns: list[str]) -> list[Path]:
    """Every existing file under ``root`` matching any of ``patterns``, deduped and sorted."""
    found: set[Path] = set()
    for pattern in patterns:
        found.update(path for path in root.glob(pattern) if path.is_file())
    return sorted(found)


def missing_artifacts(main_root: Path, manifest: NativeManifest) -> list[MissingArtifact]:
    """Declared artifacts absent from ``main_root``.

    Reasons: ``no_match`` (a ``required`` group's ``copy_globs`` match nothing),
    ``unpaired_source`` (a ``pair_sources`` match has no sibling compiled
    module), ``abi_mismatch`` (an ``abi_scoped`` group whose artifacts all carry
    a foreign ``EXT_SUFFIX``).
    """
    # FILL IN: implement the three checks in that order, one MissingArtifact per
    # finding, `detail` = the unmatched glob list or the repo-relative source path.
    # Pairing rule (verified at baseline.py:70): a source `<stem>.pyx` is paired
    # when `any(parent.glob(f"{stem}.*.so"))` or `(parent / f"{stem}.so").exists()`;
    # for an abi_scoped group the sibling must additionally end with _ext_suffix().
    # Bounded by: a group with `required=False` and no matches is NOT missing (AC-3).
    raise NotImplementedError


def sync_native_artifacts(
    *,
    main_root: Path,
    target: Path,
    manifest: NativeManifest | None = None,
) -> NativeSyncReport:
    """Copy every declared native artifact from ``main_root`` into ``target``.

    Idempotent: a destination whose size and mtime already match the source is
    reported in ``skipped``, never re-copied, so this is safe to call again on a
    reused worktree. Honours ``manifest.enabled`` and
    ``PARROT_WORKTREE_SYNC_NATIVE=0`` by returning an ``enabled=False`` report
    that copies nothing. NEVER raises for a missing artifact: it records a
    ``MissingArtifact`` plus a ``manual_hint`` warning and returns.

    Args:
        main_root: The primary checkout holding the built artifacts.
        target: The worktree to populate.
        manifest: Parsed declaration; loaded from ``main_root`` when omitted.
    """
    resolved = manifest if manifest is not None else load_manifest(main_root)
    if not resolved.enabled or env_flag_disabled(SYNC_ENV_VAR):
        return NativeSyncReport(enabled=False)
    # FILL IN: for each group, copy every `_matches(main_root, group.copy_globs)`
    # entry to `target / rel`, creating parents; skip when size+mtime match;
    # then add `missing_artifacts(main_root, resolved)` to the report and one
    # warning per missing entry quoting `group.manual_hint` when it is set.
    # Bounded by: report paths are repo-relative POSIX strings (AC-5); copy2 only.
    raise NotImplementedError
```
**Why this shape**: `main_checkout_root` and `_git` are reproduced verbatim from
`baseline.py` so TASK-4611's deletion is a pure move with no behaviour change.
`_matches` exists because both `missing_artifacts` and the copy loop need the
same glob semantics, and a set dedupes the overlapping globs. The signature of
`sync_native_artifacts` is keyword-only and has **no** `autobuild` parameter —
TASK-4608 adds it together with the build hook, so nothing here pretends to
build.

### FILL IN checklist
- [ ] `native_artifacts.py::missing_artifacts` — the three checks and their
      `detail` values; bounded by the pairing rule verified at `baseline.py:70`
      and "required=False + no matches is not missing" (AC-3).
- [ ] `native_artifacts.py::sync_native_artifacts` — the copy loop, the
      size+mtime skip and the missing/warning aggregation; bounded by
      "repo-relative paths, `copy2` only, never raises" (AC-5, AC-7).

---

## Acceptance Criteria

- [ ] `main_checkout_root(Path(".claude/worktrees/<any existing worktree>"))`
      returns the repository root; on a non-git tmp dir it returns `None`
- [ ] Copying into an empty synthetic target reproduces each source's
      repo-relative path, and every copied path appears in `report.copied`
- [ ] A second identical call copies nothing, reports every path in
      `report.skipped`, and leaves the destinations' mtimes unchanged
- [ ] A `.pyx` whose sibling compiled module is absent yields exactly one
      `MissingArtifact(reason="unpaired_source")`; a `required` group whose
      globs match nothing yields `reason="no_match"`; an `abi_scoped` group with
      only a foreign-suffix `.so` yields `reason="abi_mismatch"`
- [ ] `PARROT_WORKTREE_SYNC_NATIVE=0` and `manifest.enabled = false` each return
      `NativeSyncReport(enabled=False)` with empty `copied`
- [ ] No report field ever contains an absolute path
- [ ] A missing artifact never raises — the report carries it, and the warning
      text contains the group's `manual_hint`
- [ ] `grep -nE '^(from|import) parrot' .../native_artifacts.py` still returns nothing
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py -q` passes
- [ ] `ruff check` clean on both files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py -q`

---

## Test Specification

Add to `packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py`:

```python
import os
import sysconfig
from pathlib import Path

import pytest

from parrot.flows.dev_loop.native_artifacts import (
    SYNC_ENV_VAR,
    NativeGroup,
    NativeManifest,
    main_checkout_root,
    missing_artifacts,
    sync_native_artifacts,
)

EXT = sysconfig.get_config_var("EXT_SUFFIX") or ".so"


@pytest.fixture
def fake_main_root(tmp_path: Path) -> Path:
    """A main checkout holding one .pyx and its sibling .so for THIS interpreter."""
    pkg = tmp_path / "main" / "packages" / "demo" / "src" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "fast.pyx").write_text("# cython\n", encoding="utf-8")
    (pkg / f"fast{EXT}").write_bytes(b"\x7fELF-not-really")
    return tmp_path / "main"


@pytest.fixture
def stub_manifest() -> NativeManifest:
    return NativeManifest(
        enabled=True,
        groups=[
            NativeGroup(
                name="demo",
                copy_globs=["packages/demo/src/**/*.so"],
                pair_sources=["packages/demo/src/**/*.pyx"],
                abi_scoped=True,
                manual_hint="make demo",
            )
        ],
    )


def test_sync_copies_declared_artifacts(fake_main_root, stub_manifest, tmp_path):
    target = tmp_path / "wt"
    (target / "packages" / "demo" / "src" / "demo").mkdir(parents=True)
    report = sync_native_artifacts(main_root=fake_main_root, target=target, manifest=stub_manifest)
    assert report.enabled is True
    assert report.copied == [f"packages/demo/src/demo/fast{EXT}"]
    assert (target / f"packages/demo/src/demo/fast{EXT}").is_file()
    assert report.missing == []


def test_sync_is_idempotent(fake_main_root, stub_manifest, tmp_path):
    target = tmp_path / "wt"
    sync_native_artifacts(main_root=fake_main_root, target=target, manifest=stub_manifest)
    dest = target / f"packages/demo/src/demo/fast{EXT}"
    before = dest.stat().st_mtime_ns
    second = sync_native_artifacts(main_root=fake_main_root, target=target, manifest=stub_manifest)
    assert second.copied == []
    assert second.skipped == [f"packages/demo/src/demo/fast{EXT}"]
    assert dest.stat().st_mtime_ns == before


def test_sync_disabled_by_env(fake_main_root, stub_manifest, tmp_path, monkeypatch):
    monkeypatch.setenv(SYNC_ENV_VAR, "0")
    report = sync_native_artifacts(main_root=fake_main_root, target=tmp_path / "wt", manifest=stub_manifest)
    assert report.enabled is False
    assert report.copied == []


def test_missing_unpaired_source_detected(fake_main_root, stub_manifest):
    (fake_main_root / "packages/demo/src/demo" / f"fast{EXT}").unlink()
    missing = missing_artifacts(fake_main_root, stub_manifest)
    reasons = {entry.reason for entry in missing}
    assert "unpaired_source" in reasons or "no_match" in reasons


def test_missing_abi_mismatch_detected(fake_main_root, stub_manifest):
    pkg = fake_main_root / "packages/demo/src/demo"
    (pkg / f"fast{EXT}").rename(pkg / "fast.cpython-999-foreign.so")
    missing = missing_artifacts(fake_main_root, stub_manifest)
    assert any(entry.reason in {"abi_mismatch", "unpaired_source"} for entry in missing)


def test_main_checkout_root_on_non_git_dir(tmp_path):
    assert main_checkout_root(tmp_path) is None


def test_missing_never_raises_and_warns_with_hint(fake_main_root, stub_manifest, tmp_path):
    (fake_main_root / "packages/demo/src/demo" / f"fast{EXT}").unlink()
    report = sync_native_artifacts(main_root=fake_main_root, target=tmp_path / "wt", manifest=stub_manifest)
    assert report.missing
    assert any("make demo" in warning for warning in report.warnings)
```

Note on `test_missing_unpaired_source_detected` / `test_missing_abi_mismatch_detected`:
tighten each to the single expected `reason` once the classification order is
implemented — the `or` above is deliberately loose only because the order of the
three checks is a FILL IN decision.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-4606 must be `"done"`; this task edits the
   module that task creates
4. **Verify the Codebase Contract** — re-read `baseline.py:28-76` and confirm
   `main_checkout_root` and the pairing check still look as quoted; if they
   changed, update the contract first
5. **Update status** in the per-spec index → `"in-progress"`, commit only it
6. **Implement** — complete both `# FILL IN:` markers; do not add an
   `autobuild` parameter (TASK-4608 owns it)
7. **Verify** the acceptance criteria — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the two files this task lists
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4607 worktree-native-artifact-sync verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (orchestrator) — seat: gpt-5.6-terra (codex), 1 attempt
**Date**: 2026-10-22
**Notes**: Extended native_artifacts.py with the sync core and tests. test_native_artifacts.py passes (see run).

**Deviations from spec**: none
