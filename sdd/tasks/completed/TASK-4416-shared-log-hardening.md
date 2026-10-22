# TASK-4416: Shared-log hardening — crash-safe rotation, kind filter, newline, path digest, pre-import scope, CLI error handling

**Feature**: FEAT-694 — Shared Ledger Event Log (cross-machine sync via git hooks)
**Spec**: `sdd/specs/ledger-shared-event-log.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4408
**Assigned-to**: unassigned
**Discovered-from**: `issue:d436426cd1d9`

---

## Context

Code-review findings from the FEAT-694 spec review (issue:d436426cd1d9). All items harden
code created by TASK-4405/4406/4408; none changes a public interface or adds a new command.
Runs after TASK-4408 (rotation + claim pre-import exist) and before TASK-4409 (docs/integration).

---

## Scope

Seven hardening items, all in `shared_log.py` unless noted:

1. **Crash-safe rotation** — `rotate_events` appends to archive files *before* `os.replace`
   of the current file. A crash between the two steps duplicates lines in the archive.
   Fix: when appending to an existing archive, read its `event_id` set first and skip lines
   already present. Cost: one extra read per touched archive per rotation (infrequent).

2. **Rotation kind filter** — rotation currently moves every non-`issue.*` event. Spec §2
   filter says only `task.*`, `spec.*`, `insight.*` are shareable (`is_shareable`). Align
   the rotation predicate: a line is rotatable only if `is_shareable(kind)` returns `True`
   (not just `not kind.startswith("issue.")`).

3. **Trailing newline on export append** — `export_events` appends lines to the committed
   file without checking whether the existing file ends in `\n`. If the file was hand-edited
   or truncated, the first appended line merges with the last existing line.
   Fix: if the destination file is non-empty and its last byte is not `\n`, prepend `\n` to
   the first written line.

4. **Path digest — use `relative_to(repo_root)`** — `digest_files` / `_stable_relative_path`
   locate the `sdd/` path component by splitting on the first `'sdd'` segment. This breaks
   when the repo lives under a directory also named `sdd`.
   Fix: use `path.relative_to(repo_root)` (the `repo_root` parameter is already available)
   and fall back to the `'sdd'` split only when `relative_to` raises `ValueError`.

5. **`claim()` pre-import: check `shared_log_files()`** — TASK-4408 gates the pre-import on
   `(self.shared_root / SHARED_LOG_REL_PATH).exists()`. This misses the archives. Use
   `bool(shared_log_files(self.shared_root))` instead — it returns a non-empty list when any
   committed log file exists (archives or current).

6. **CLI `--stage` CalledProcessError** — `ledger export-log --stage` and
   `ledger import-log --stage` run `subprocess.run(["git", ...], check=True)`. If `git add`
   fails (e.g. detached HEAD, permissions), the `CalledProcessError` propagates as a traceback.
   Fix: catch `subprocess.CalledProcessError`, log the stderr, and `click.echo` a one-line
   error + `sys.exit(1)`.

7. **Spec §1 FEAT-671 superseded marker (AC13)** — spec §1 Problem Statement references
   FEAT-671's non-goals but does not mark them as superseded by FEAT-694. Add the marker.
   *(This item is applied directly to the spec on `dev` as part of this task's commit.)*

**NOT in scope**: new commands, new models, rotation policy changes, anything in TASK-4409/4410.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py` | MODIFY | Items 1-4 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | Item 5 (claim pre-import) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Item 6 (CalledProcessError) |
| `sdd/specs/ledger-shared-event-log.spec.md` | MODIFY | Item 7 (FEAT-671 marker) |
| `tests/knowledge/wiki/test_ledger_shared_log.py` | MODIFY | Add crash-safe rotation + newline tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.shared_log import (   # created by TASK-4405
    SHARED_LOG_REL_PATH, is_shareable, shared_log_files,
    read_raw_events, digest_files, export_events,
)
from parrot.knowledge.wiki.ledger.shared_log import rotate_events  # added by TASK-4408
```

### Existing Signatures to Use
```python
# shared_log.py (created by TASK-4405, extended by TASK-4408)
def is_shareable(kind: str) -> bool                     # TASK-4405 — True for task.*/spec.*/insight.*
def shared_log_files(repo_root: Path) -> list[Path]     # TASK-4405 — archives (sorted) + current
def digest_files(files: list[Path]) -> str              # TASK-4405 — SHA-256 of concatenated content
def export_events(local_log_path, repo_root, ...) -> SharedLogExportReport  # TASK-4405
def rotate_events(repo_root, *, older_than_days=30, now=None) -> SharedLogRotateReport  # TASK-4408

# service.py (modified by TASK-4408)
async def claim(self, issue_id: str, actor: str) -> bool  # TASK-4408 adds pre-import
```

### Does NOT Exist
- ~~`_stable_relative_path`~~ — internal helper in `shared_log.py`; name may differ; grep before editing
- ~~`shared_log.py` on disk right now~~ — created by TASK-4405; this task runs AFTER TASK-4408

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY"},
    {"path": "sdd/specs/ledger-shared-event-log.spec.md", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_shared_log.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Item 1 — Crash-safe rotation
In `rotate_events`, before appending moved lines to an archive file:
```python
existing_ids: set[str] = set()
if archive_path.exists():
    for line in archive_path.read_text().splitlines():
        try:
            existing_ids.add(json.loads(line)["event_id"])
        except (json.JSONDecodeError, KeyError):
            pass
# skip lines whose event_id is in existing_ids
```

### Item 2 — Rotation kind filter
Replace the `not kind.startswith("issue.")` predicate with `is_shareable(kind)`. The
`is_shareable` function (TASK-4405) already encodes the spec's filter.

### Item 3 — Trailing newline
In `export_events`, before the first `write()`:
```python
if dest.stat().st_size > 0:
    with open(dest, "rb") as f:
        f.seek(-1, 2)
        if f.read(1) != b"\n":
            lines_to_write[0] = "\n" + lines_to_write[0]
```

### Item 4 — Path digest
In `digest_files` / `_stable_relative_path`:
```python
try:
    rel = path.relative_to(repo_root)
except ValueError:
    rel = _legacy_sdd_split(path)  # fallback
```

### Item 5 — claim pre-import scope
In `service.py` `claim()`, replace:
```python
if (self.shared_root / SHARED_LOG_REL_PATH).exists():
```
with:
```python
if shared_log_files(self.shared_root):
```

### Item 6 — CLI CalledProcessError
Wrap the `subprocess.run(["git", ...], check=True)` calls in `ledger_export_log` and
`ledger_import_log` (and `ledger_rotate_log`):
```python
try:
    subprocess.run([...], check=True, capture_output=True, text=True)
except subprocess.CalledProcessError as exc:
    click.echo(f"git add failed: {exc.stderr.strip()}", err=True)
    sys.exit(1)
```

---

## Implementation Blueprint

### Steps (in order)
1. Edit `shared_log.py` for items 1-4 — *why*: crash safety, correctness, robustness
2. Edit `service.py` for item 5 — *why*: claim sees archives, not just current file
3. Edit `cli.py` for item 6 — *why*: user-facing error instead of traceback
4. Edit spec for item 7 — *why*: AC13 compliance
5. Add/extend tests for items 1, 3 — *why*: regression coverage

### FILL IN checklist
- [ ] `rotate_events` dedup by event_id against existing archive content
- [ ] `rotate_events` kind predicate uses `is_shareable`
- [ ] `export_events` newline guard
- [ ] `digest_files` / `_stable_relative_path` uses `relative_to(repo_root)`
- [ ] `claim()` uses `shared_log_files()` instead of `SHARED_LOG_REL_PATH.exists()`
- [ ] CLI `--stage` catches CalledProcessError
- [ ] Spec §1 FEAT-671 superseded marker

---

## Acceptance Criteria

- [ ] Rotation into an existing archive never duplicates lines (test with pre-populated archive)
- [ ] Rotation predicate matches `is_shareable`, not `not kind.startswith("issue.")`
- [ ] Export appends a leading `\n` when the committed file doesn't end with one
- [ ] `digest_files` produces the same digest regardless of repo parent path
- [ ] `claim()` triggers import when only archives exist (no `events.jsonl`)
- [ ] `--stage` failure prints a one-line error, not a traceback
- [ ] Spec §1 has the FEAT-671 superseded marker (AC13)
- [ ] `ruff check` clean on all touched files
- [ ] All existing FEAT-694 tests still pass

## Validation Commands

- `pytest tests/knowledge/wiki/test_ledger_shared_log.py -q`
- `pytest tests/knowledge/wiki/test_ledger_shared_log_rotation.py -q`
- `pytest tests/knowledge/wiki/test_cli_ledger_shared_log.py -q`

---

## Test Specification

Extend the existing FEAT-694 test files:

```python
# tests/knowledge/wiki/test_ledger_shared_log.py — add to existing M1 tests
def test_export_ensures_trailing_newline(tmp_path):
    """Export prepends \\n when committed file doesn't end with one."""

def test_digest_stable_across_repo_paths(tmp_path):
    """digest_files result is the same regardless of parent directory name."""
```

```python
# tests/knowledge/wiki/test_ledger_shared_log_rotation.py — add to existing M5 tests
def test_rotate_dedup_against_existing_archive(tmp_path):
    """Crash-recovery: lines already in archive are not duplicated on re-rotation."""

def test_rotate_kind_filter_matches_is_shareable(tmp_path):
    """Only events where is_shareable(kind) rotates; others stay in current."""
```

---

## Agent Instructions

Standard SDD flow; feature worktree `feat-FEAT-694-ledger-shared-event-log`;
`PYTHONPATH=packages/ai-parrot/src`; close with
`scripts/sdd/close_task.sh TASK-4416 ledger-shared-event-log verified`.

**Note**: the spec edit (item 7) is a shared artifact — commit it on the feature branch,
not on `dev`. It will merge with the rest of the feature.

---

## Completion Note

**Completed by**: sdd-worker (code by seat gpt-5.6-luna, attempt 2; attempt 1 gpt-5.6-terra delivered nothing)
**Date**: 2026-10-22
**Notes**: Items 1-6 implemented in shared_log.py / service.py / cli.py; item 7 (FEAT-671 superseded marker) was already present in spec §1 (line 31), so the spec was not touched. `import-log` has no `--stage`, so only `export-log` and `rotate-log` got the CalledProcessError handling. Worker fixed an over-indented try block in cli.py (commit a4be44176). Merge-tier validation: 608 passed, 7 skipped, exit 0 (twice), but the engine labelled the outcome `timed_out` despite ~40s runtime, so it was not accepted as a formal green; targeted FEAT-694 tests (43) were also run directly and passed; ruff clean.

**Deviations from spec**: The task's Files table omitted `tests/knowledge/wiki/test_ledger_shared_log_rotation.py` and `test_cli_ledger_shared_log.py`, although its Test Specification and Validation Commands name them. The engine flagged them as fidelity_violation; the worker committed them manually as the task's own Test Specification requires. No feedback recorded (the task-doc inconsistency was not a model defect).
