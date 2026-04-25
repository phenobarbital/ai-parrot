# TASK-854: Verify existing FileManager-consuming tests after migration

**Feature**: FEAT-123 — fileinterface-migration
**Spec**: `sdd/specs/fileinterface-migration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-851, TASK-852, TASK-853
**Assigned-to**: unassigned

---

## Context

Two test modules exercise `FileManagerInterface` /
`LocalFileManager` / `TempFileManager` indirectly:

- `packages/ai-parrot/tests/storage/test_overflow_store.py`
- `packages/ai-parrot/tests/test_video_reel_storage.py`

Both use `MagicMock(spec=FileManagerInterface)` /
`AsyncMock(spec=FileManagerInterface)` and inspect concrete
classes by name (e.g.
`type(fm).__name__ == "LocalFileManager"`). After TASK-851 the
spec class is the upstream
`navigator.utils.file.abstract.FileManagerInterface`, which adds
`find_files`, `create_folder`, `remove_folder`, `rename_folder`,
`rename_file`, and `manager_name`. None of these should affect
the tests, but the suite must be run end-to-end to confirm — and
any drift fixed at minimum scope.

This is a verification task: run the suite, fix only what breaks
because of the shim, and document anything that needed to change.
Implements **Module 7** of the spec.

---

## Scope

- Run the full pytest suite for both target modules under the
  activated venv:
  ```bash
  source .venv/bin/activate
  pytest packages/ai-parrot/tests/storage/test_overflow_store.py -v
  pytest packages/ai-parrot/tests/test_video_reel_storage.py -v
  ```
- If both pass: no code change. Move the task to completed and
  record "no edits required" in the completion note.
- If any test fails because of the shim (e.g., a `spec=` mock
  call now exposes a method that an `assert_called_with` did
  not anticipate, or a `type(fm).__name__` check needs a
  module-path tweak), fix only that test with the **smallest
  possible change**. Examples of acceptable fixes:
  - Updating `assert type(fm).__name__ == "LocalFileManager"`
    to `assert isinstance(fm, LocalFileManager)` if the
    name-equality assertion was load-bearing on the local
    duplicate.
  - Adjusting a `MagicMock(spec=FileManagerInterface)` to
    explicitly set the methods the test cares about, if a new
    upstream method gets auto-mocked in a way that breaks an
    assertion.
- If a test fails for a reason unrelated to the migration
  (e.g. an unrelated import error, network call), do NOT
  attempt to fix it; report it in the completion note and
  treat it as out of scope.
- Run a broader sanity sweep of the whole storage subpath:
  ```bash
  pytest packages/ai-parrot/tests/storage/ -v
  ```
  to catch indirect breakage in the OverflowStore / S3OverflowStore
  consumers.

**NOT in scope**:
- Adding new tests (TASK-853 already covers the shim).
- Refactoring either test module beyond the minimum needed to
  keep them green.
- Touching `parrot/interfaces/file/*` (TASK-851) or
  `parrot/tools/filemanager.py` (TASK-852).
- Bulk-renaming `LocalFileManager` test labels or rewriting
  fixtures.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/storage/test_overflow_store.py` | MAYBE MODIFY | Only if a test breaks because of the shim; minimum-change fix. |
| `packages/ai-parrot/tests/test_video_reel_storage.py` | MAYBE MODIFY | Only if a test breaks because of the shim; minimum-change fix. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports — these MUST keep working after the shim

```python
# tests/storage/test_overflow_store.py:8
from parrot.interfaces.file.abstract import FileManagerInterface

# tests/storage/test_overflow_store.py:69
from parrot.interfaces.file.s3 import S3FileManager

# tests/test_video_reel_storage.py:23
from parrot.interfaces.file import FileManagerInterface
```

### Existing Signatures to Use

```python
# tests/test_video_reel_storage.py:97-106 — existing assertions on factory output
def test_local_backend(...):
    """'fs' backend creates a LocalFileManager."""
    assert isinstance(fm, FileManagerInterface)
    assert type(fm).__name__ == "LocalFileManager"
# Note: name-string equality survives the migration because the
# upstream class is also named "LocalFileManager".
```

```python
# tests/storage/test_overflow_store.py:14
fm = MagicMock(spec=FileManagerInterface)
# After TASK-851 this spec resolves to navigator.utils.file.abstract.FileManagerInterface,
# which adds: find_files, create_folder, remove_folder, rename_folder, rename_file, manager_name.
```

### Does NOT Exist

- ~~Any failure mode where `type(fm).__name__ == "LocalFileManager"`
  stops being true~~ — upstream's class is also named
  `LocalFileManager`. The string check survives.
- ~~`MagicMock(spec=FileManagerInterface)` will lose existing
  attributes~~ — `spec=` is **additive**: it adds the spec's
  members but does not remove any. Existing
  `fm.upload_file.return_value = ...` lines keep working.
- ~~A test failure means the migration is wrong~~ — most
  failures here would indicate over-strict mock assertions
  rather than a regression. Fix the test, not the migration,
  unless the shim itself is mis-wired (in which case go back
  to TASK-851).

---

## Implementation Notes

### Pattern to Follow

This is largely a **diagnose-only** task. The expected outcome
is:

> "Both modules pass with zero edits."

The fix patterns, only if needed:

```python
# If a name-equality assertion is load-bearing and breaks for any reason:
- assert type(fm).__name__ == "LocalFileManager"
+ from parrot.interfaces.file import LocalFileManager
+ assert isinstance(fm, LocalFileManager)
```

```python
# If a MagicMock(spec=...) call leaks new auto-mocks into a strict
# assertion list (extremely unlikely but possible):
- fm = MagicMock(spec=FileManagerInterface)
+ fm = MagicMock(spec=FileManagerInterface)
+ # If your test relied on dir(fm) being exactly the old shape:
+ for new_attr in ("find_files", "create_folder", "remove_folder",
+                  "rename_folder", "rename_file"):
+     ...  # delete or stub explicitly per the failing assertion
```

### Key Constraints

- Smallest possible diff. If a test was loose enough to keep
  passing, do not touch it.
- Do not refactor test setup, fixtures, or naming in the
  course of this task.
- Do not introduce new dependencies, fixtures, or helpers.
- Capture every test that needed an edit in the completion
  note (file + test name + reason).

### References in Codebase

- `packages/ai-parrot/tests/storage/test_overflow_store.py` —
  primary target.
- `packages/ai-parrot/tests/test_video_reel_storage.py` —
  primary target.
- `packages/ai-parrot/src/parrot/handlers/video_reel.py:79-100` —
  the factory function those tests exercise (helps interpret
  failures).
- `packages/ai-parrot/src/parrot/storage/overflow.py` and
  `s3_overflow.py` — consumers under test in the storage suite.

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/storage/test_overflow_store.py -v`
      → all tests pass.
- [ ] `pytest packages/ai-parrot/tests/test_video_reel_storage.py -v`
      → all tests pass.
- [ ] `pytest packages/ai-parrot/tests/storage/ -v` → all tests
      pass (or any failures are documented in the completion
      note as pre-existing / unrelated to FEAT-123).
- [ ] Any modifications to test files are minimum-scope and
      individually justified in the completion note.
- [ ] No test was deleted, skipped, or marked `xfail` to make
      the suite pass.
- [ ] `ruff check` clean on any modified test files.

---

## Test Specification

This task is itself the verification step; no new tests are
added here. The acceptance check is the pytest output.

```bash
source .venv/bin/activate

# Targeted runs
pytest packages/ai-parrot/tests/storage/test_overflow_store.py -v
pytest packages/ai-parrot/tests/test_video_reel_storage.py -v

# Broader sanity sweep
pytest packages/ai-parrot/tests/storage/ -v

# Combined regression with the shim test from TASK-853
pytest packages/ai-parrot/tests/interfaces/test_file_shim.py \
       packages/ai-parrot/tests/storage/ \
       packages/ai-parrot/tests/test_video_reel_storage.py -v
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** — TASK-851, TASK-852, TASK-853 must
   all be in `sdd/tasks/completed/`.
3. **Update status** in `sdd/tasks/.index.json` →
   `"in-progress"` with your session ID.
4. Run the four pytest commands above. Save output to
   `artifacts/logs/feat-123-verify-tests.log` (per CLAUDE.md
   "Save evidence to artifacts/logs/").
5. If everything passes, document "no edits required" and
   move on. If any test fails, fix only the migration-caused
   failures with minimum-scope edits.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to
   `sdd/tasks/completed/TASK-854-verify-existing-storage-tests.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
