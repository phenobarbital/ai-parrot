# TASK-4611: Refactor baseline.py onto the shared native-artifact sync

**Feature**: FEAT-722 — Worktree Native Artifact Sync
**Spec**: `sdd/specs/worktree-native-artifact-sync.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4608
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (de-duplication half). `prepare_baseline_checkout()` already
does what this whole feature generalises: it copies `packages/*/src/**/*.so`
from the main checkout into a fresh checkout and refuses the checkout when a
`.pyx` has no sibling `.so` (`baseline.py:56-76`). It was simply never shared.

After this task there is ONE implementation. `baseline.py` keeps its stricter
contract — a missing artifact is fatal there, because a baseline run that
cannot import the extension would report false "unknown" verdicts — but it
expresses that by inspecting the report instead of walking the tree itself.

`main_checkout_root` also finishes its move here: TASK-4607 added a copy in
`native_artifacts.py`, and this task deletes `baseline.py`'s definition and
imports the shared one.

---

## Scope

- Delete `main_checkout_root` from `baseline.py` and import it (plus
  `sync_native_artifacts`) from `..native_artifacts`.
- Replace the `.so` copy loop and the `.pyx` pairing check
  (`baseline.py:60-71`) with one `sync_native_artifacts(..., autobuild=False)`
  call plus a `BaselineUnavailable` raise when `report.missing` is non-empty.
- Keep `_git`, `prepare_baseline_checkout`'s signature, its cleanup-on-failure
  behaviour and its error-message shape unchanged.
- Confirm `test_scope/test_baseline.py` passes **unmodified**; add one test
  pinning the "unbuilt extension is still fatal" contract.

**NOT in scope**: changing when `prepare_baseline_checkout` is called;
`autobuild` for baseline (explicitly `False` — a verdict run must not trigger a
compile); any other `test_scope` module.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py` | MODIFY | Use the shared sync; drop the local copy loop and `main_checkout_root` |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py` | MODIFY | Add the "missing artifact is still fatal" test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already in baseline.py
import logging, os, shutil, subprocess, sys, tempfile   # verified: baseline.py:9-15
from pathlib import Path                                 # verified: baseline.py:16
from .datatypes import BaselineVerdict                   # verified: baseline.py:18
from .mirror import distribution_of                      # verified: baseline.py:19
from .report import parse_junit                          # verified: baseline.py:20

# added by THIS task
from ..native_artifacts import main_checkout_root, sync_native_artifacts
# NOTE the TWO dots: baseline.py is at parrot/flows/dev_loop/test_scope/, the
# module at parrot/flows/dev_loop/. `shutil` may become unused — check before
# removing it (remove_baseline_checkout / other helpers may still use it).
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py
class BaselineUnavailable(RuntimeError):                               # line 25
def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:   # line 28 — KEEP
def main_checkout_root(worktree: Path) -> Path | None:                 # line 34 — DELETE (moved)
def prepare_baseline_checkout(*, worktree: Path, base_ref: str, scratch: Path) -> Path:  # line 45 — signature UNCHANGED
    add = _git(worktree, "worktree", "add", "--detach", str(target), sha)   # line 55
    try:
        main_root = main_checkout_root(worktree)                        # line 60
        if main_root is not None:                                       # line 61
            for so_file in main_root.glob("packages/*/src/**/*.so"):    # line 62 (occurrences: 1) — REPLACE
                rel = so_file.relative_to(main_root)                    # line 63
                dest = target / rel                                     # line 64
                if dest.exists() or not dest.parent.is_dir():           # line 65
                    continue                                            # line 66
                shutil.copy2(so_file, dest)                             # line 67
        for pyx in target.glob("packages/*/src/**/*.pyx"):              # line 69
            stem = pyx.stem                                             # (line 69-70)
            if not any(pyx.parent.glob(f"{stem}.*.so")) and not (pyx.parent / f"{stem}.so").exists():  # line 70
                raise BaselineUnavailable(f"no compiled extension for {pyx.relative_to(target)} in main checkout")  # line 71
    except BaselineUnavailable:
        remove_baseline_checkout(worktree, target); raise               # lines 72-74
    except OSError as exc:
        remove_baseline_checkout(worktree, target)                      # lines 75-77
        raise BaselineUnavailable(f"copying compiled artifacts failed: {exc}") from exc
    return target                                                       # line 78
def remove_baseline_checkout(worktree: Path, path: Path) -> None:       # line 81 — KEEP
```

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py (TASK-4606..4608)
def main_checkout_root(worktree: Path) -> Path | None     # byte-identical logic to baseline's
def sync_native_artifacts(*, main_root: Path, target: Path,
                          manifest: NativeManifest | None = None,
                          autobuild: bool = True) -> NativeSyncReport
class MissingArtifact:  # group: str, reason: str, detail: str
```

```python
# packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py
@pytest.fixture
def hermetic_repo(tmp_path: Path):                     # line 27
def test_unbuildable_base_is_unknown(hermetic_repo, tmp_path):   # line 69
def test_non_pytest_failure_is_unknown_without_checkout(hermetic_repo, monkeypatch):  # line 84
    monkeypatch.setattr(baseline, "prepare_baseline_checkout", fail_if_called)        # line 90
def test_checkout_always_removed(hermetic_repo, tmp_path):       # line 101
```

### Does NOT Exist
- ~~`from parrot.flows.dev_loop.native_artifacts import ...`~~ as an *absolute*
  import in this file — `baseline.py` uses relative imports (`.datatypes`,
  `.mirror`, `.report`), so use `..native_artifacts`.
- ~~another importer of `baseline.main_checkout_root`~~ — verified:
  `grep -rn "main_checkout_root" --include=*.py packages/` matches only
  `baseline.py:34` (the definition) and `:60` (its own use). Deleting it breaks
  nothing outside this file. Re-run that grep before deleting.
- ~~`autobuild=True` for baseline~~ — a verdict run must never trigger a
  compile; pass `autobuild=False` explicitly.
- ~~a `NativeSyncReport.ok` / `.success` attribute~~ — the report has
  `enabled, copied, skipped, built, missing, warnings` and nothing else.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py#prepare_baseline_checkout",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py#main_checkout_root",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py#sync_native_artifacts"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Behaviour must not change.** `test_baseline.py` passes unmodified except for
  the one test this task adds. If a pre-existing test needs editing, stop — that
  means the refactor changed semantics.
- **One intentional, equivalent difference**: the old pairing check scanned the
  *target* tree after copying; `missing_artifacts` inspects the *main checkout*.
  Both answer "is the extension built in the main checkout" — the old code could
  only see sources that exist in the base ref, the new one sees the declaration.
  Keep the message shape `"no compiled extension for <detail> in main checkout"`
  so the existing assertions and operator expectations still match.
- The `except OSError` arm stays: `sync_native_artifacts` does not raise for a
  missing artifact, but a genuinely broken filesystem still can.
- Check whether `shutil` is still used after the copy loop goes; remove the
  import only if it is not (ruff F401 will tell you).

---

## Implementation Blueprint

### Steps (in order)
1. Add the relative import and delete `baseline.py`'s `main_checkout_root`
   — *why*: one definition, and `native_artifacts` is the module three callers
   share.
2. Replace the copy loop + pairing check with the shared call — *why*: this is
   the de-duplication the whole module exists for; `autobuild=False` keeps a
   verdict run from compiling anything.
3. Add the regression test — *why*: "an unbuilt extension is fatal here" is the
   one behaviour a future reader would assume the shared helper relaxed.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py` (MODIFY — 1 of 2)
```python
# occurrences: 1 (verified: grep -c 'def main_checkout_root(worktree: Path) -> Path | None:' packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py)
# DELETE the whole `main_checkout_root` function (verified: baseline.py:34-42)
# and ADD this import below `from .report import parse_junit` (verified: baseline.py:20):
from ..native_artifacts import main_checkout_root, sync_native_artifacts
```
**Why**: importing the name keeps `baseline.main_checkout_root` resolvable for
anything that referenced it through this module, while the single definition
now lives beside the sync that uses it.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py` (MODIFY — 2 of 2)
```python
# occurrences: 1 (verified: grep -c '            for so_file in main_root.glob("packages/*/src/**/*.so"):' packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py)
# REPLACE lines 60-71 — the `main_root = ...` block, the `.so` copy loop and the
# `.pyx` pairing check (verified: baseline.py:60-71) — with:
        main_root = main_checkout_root(worktree)
        if main_root is not None:
            # One shared implementation (FEAT-722). `autobuild=False`: a verdict
            # run must never trigger a compile, so an unbuilt extension stays
            # fatal here rather than being repaired behind the operator's back.
            report = sync_native_artifacts(main_root=main_root, target=target, autobuild=False)
            if report.missing:
                detail = report.missing[0].detail
                raise BaselineUnavailable(f"no compiled extension for {detail} in main checkout")
```
**Why**: the surrounding `try` / `except BaselineUnavailable` / `except OSError`
arms (lines 59, 72-77) and the trailing `return target` stay exactly as they
are, so the cleanup-on-failure contract is untouched. Only the body changes.

### FILL IN checklist
- [ ] none for the two blocks above. Judgement remains in the added test and in
      deciding whether `shutil` is still used (let `ruff` answer).

---

## Acceptance Criteria

- [ ] `baseline.py` contains no `.so`/`.pyx` glob loop:
      `grep -nE '\*\.so|\*\.pyx' .../test_scope/baseline.py` returns nothing
- [ ] `baseline.py` defines `main_checkout_root` nowhere and imports it from
      `..native_artifacts`
- [ ] `prepare_baseline_checkout` still has exactly its line-45 signature
- [ ] `prepare_baseline_checkout` still raises `BaselineUnavailable` when the
      main checkout has an unpaired source, and the message still reads
      `no compiled extension for … in main checkout`
- [ ] The failing path still removes the checkout (the pre-existing
      `test_checkout_always_removed` passes unmodified)
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py -q`
      passes with no edits to any pre-existing test
- [ ] `grep -rn "main_checkout_root" --include=*.py packages/ | grep -v "/build/"`
      shows the definition only in `native_artifacts.py`
- [ ] `ruff check` clean on both files (no unused `shutil` import left behind)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py -q`

---

## Test Specification

Add to `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py`,
reusing its `hermetic_repo` fixture (line 27):

```python
def test_baseline_checkout_still_refuses_unbuilt_extension(hermetic_repo, tmp_path):
    """An unpaired source in the main checkout is still fatal after the refactor.

    Declare a stub group in the hermetic repo (or monkeypatch
    `baseline.sync_native_artifacts` to return a report carrying one
    MissingArtifact) and assert `prepare_baseline_checkout` raises
    BaselineUnavailable with a message containing "no compiled extension for",
    and that the checkout directory no longer exists afterwards.
    """
```

Write the real body. Do not change any existing test in this file — if one
fails, the refactor altered behaviour and must be corrected instead.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-4608 must be `"done"` (the `autobuild`
   parameter is used here)
4. **Verify the Codebase Contract** — re-run the two `grep -c` commands AND the
   `main_checkout_root` importer grep before deleting anything
5. **Update status** in the per-spec index → `"in-progress"`, commit only it
6. **Implement** — apply both blocks; keep every surrounding `try`/`except` arm
7. **Verify** the acceptance criteria — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the two files this task lists
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4611 worktree-native-artifact-sync verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
