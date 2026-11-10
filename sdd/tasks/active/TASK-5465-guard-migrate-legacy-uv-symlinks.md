# TASK-5465: Guard `migrate_legacy_uv` against symlinked legacy `bin/uv`

**Feature**: FEAT-872 — Guard `migrate_legacy_uv` Against Symlinked Legacy `bin/uv`
**Spec**: `sdd/specs/self--uv-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:d08792fd4747`

---

## Context

`legacy_uv_files()` checks `path.is_file()` under `parrot_home() / "bin"`, which follows symlinks, and `migrate_legacy_uv()` calls `os.replace(bin_uv, managed_uv())` when `bin_uv` is in range and no managed, recorded, or separate `PATH` `uv` was found. A legacy `~/.parrot/bin/uv` symlink pointing to the user's own `uv` installation would therefore be moved into `libexec`. Implements spec §2, Module 1.

---

## Scope

- Update `legacy_uv_files()` in `packages/ai-parrot/src/parrot/self_/uv.py` to detect both symlinks and regular files (`path.is_symlink() or path.is_file()`).
- Update `migrate_legacy_uv()` in `packages/ai-parrot/src/parrot/self_/uv.py` so:
  1. When `bin_uv` is a symlink (`bin_uv.is_symlink()`), `os.replace(bin_uv, managed_uv())` is never executed;
  2. When no managed, recorded, or `PATH` `uv` is found and `bin_uv` is a symlink whose resolved target (`bin_uv.resolve(strict=False)`) is outside `{_resolved(parrot_home() / "bin"), _resolved(libexec_dir())}` and `_compatible(target)`, record that target via `record_system_uv(target)` before unlinking the symlink;
  3. The cleanup loop unlinks legacy entries with `if path.is_symlink() or path.exists(): path.unlink()`.
- Add unit tests in `packages/ai-parrot/tests/self_/test_uv.py` covering symlinked `bin/uv` migration (with and without `PATH` `uv`, and broken symlinks).

**NOT in scope**: `resolve_uv()`, `find_path_uv()`, `record_system_uv()`, or installer shell scripts.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/self_/uv.py` | MODIFY | Guard `migrate_legacy_uv` and `legacy_uv_files` against symlinks |
| `packages/ai-parrot/tests/self_/test_uv.py` | MODIFY | Add unit tests for symlinked legacy `bin/uv` migration |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

Verified against `origin/dev` @ `f4d5ba1b9e`.

### Verified Imports
```python
from parrot.launcher import parrot_home  # verified: packages/ai-parrot/src/parrot/self_/uv.py:15
from parrot.self_ import uv  # verified: packages/ai-parrot/tests/self_/test_uv.py:10
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/self_/uv.py
def _exe(name: str) -> str:  # line 37
def _resolved(path: Path) -> str:  # line 42
def libexec_dir() -> Path:  # line 50
def managed_uv() -> Path:  # line 55
def uv_path_file() -> Path:  # line 60
def legacy_uv_files() -> list[Path]:  # line 65
def find_path_uv() -> Path | None:  # line 105
def read_recorded_uv() -> Path | None:  # line 115
def record_system_uv(path: Path) -> Path:  # line 125
def _compatible(path: Path | None) -> str | None:  # line 135
def migrate_legacy_uv() -> list[str]:  # line 174
```

### Does NOT Exist
- No helper outside `Path.is_symlink` / `Path.resolve`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/self_/uv.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/self_/test_uv.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/self_/uv.py#legacy_uv_files",
    "sym:packages/ai-parrot/src/parrot/self_/uv.py#migrate_legacy_uv",
    "sym:packages/ai-parrot/tests/self_/test_uv.py#test_migrate_keeps_files_when_nothing_is_compatible"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Never call `os.replace(bin_uv, managed_uv())` when `bin_uv.is_symlink()` is `True`.
- Unlink only the symlink under `parrot_home() / "bin"`, leaving the user's underlying `uv` binary untouched.

### References in Codebase
- `packages/ai-parrot/src/parrot/self_/uv.py:65-69` (`legacy_uv_files`)
- `packages/ai-parrot/src/parrot/self_/uv.py:174-200` (`migrate_legacy_uv`)
- `packages/ai-parrot/tests/self_/test_uv.py:90-124` (migration unit tests)

---

## Implementation Blueprint

### Steps (in order)
1. Update `legacy_uv_files()` and `migrate_legacy_uv()` in `packages/ai-parrot/src/parrot/self_/uv.py` — *why*: prevent `os.replace` from moving a symlink into `libexec`, record a compatible external symlink target when no other `uv` is found, and unlink only the legacy link.
2. Add symlink migration unit tests in `packages/ai-parrot/tests/self_/test_uv.py` — *why*: verify that a `bin/uv` symlink to the user's `uv` is unlinked without moving or modifying the target binary.

### `packages/ai-parrot/src/parrot/self_/uv.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def legacy_uv_files() -> list\[Path\]:' packages/ai-parrot/src/parrot/self_/uv.py)
# REPLACE lines 65-69 (`def legacy_uv_files() -> list[Path]: ...`) with:
def legacy_uv_files() -> list[Path]:
    """Return legacy uv and uvx files or symlinks under ``parrot_home()/bin``."""
    bin_dir = parrot_home() / "bin"
    return [
        path
        for path in (bin_dir / _exe("uv"), bin_dir / _exe("uvx"))
        if path.is_symlink() or path.is_file()
    ]


# occurrences: 1 (verified: grep -c 'def migrate_legacy_uv() -> list\[str\]:' packages/ai-parrot/src/parrot/self_/uv.py)
# REPLACE lines 174-200 (`def migrate_legacy_uv() -> list[str]: ...`) with:
def _symlink_target_uv(link: Path) -> Path | None:
    """Return a compatible external uv target for a legacy ``bin/uv`` symlink, if any."""
    if not link.is_symlink():
        return None
    try:
        target = link.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    own = {_resolved(parrot_home() / "bin"), _resolved(libexec_dir())}
    if target.parent and _resolved(target.parent) in own:
        return None
    return target if _compatible(target) else None


def migrate_legacy_uv() -> list[str]:
    """Move a legacy bin uv layout into libexec or record a compatible system uv."""
    legacy = legacy_uv_files()
    if not legacy:
        return []
    log: list[str] = []
    bin_uv = parrot_home() / "bin" / _exe("uv")
    if _compatible(managed_uv()) or _compatible(read_recorded_uv()):
        pass
    elif (system := find_path_uv()) is not None and _compatible(system):
        record_system_uv(system)
        log.append(f"using your uv at {system}: recorded in {uv_path_file()}")
    elif bin_uv in legacy and (target := _symlink_target_uv(bin_uv)) is not None:
        record_system_uv(target)
        log.append(f"using your uv at {target}: recorded in {uv_path_file()}")
    elif bin_uv in legacy and not bin_uv.is_symlink() and _compatible(bin_uv):
        libexec_dir().mkdir(parents=True, exist_ok=True)
        os.replace(bin_uv, managed_uv())
        log.append(f"moved {bin_uv} to {managed_uv()} (off PATH)")
    else:
        log.append(
            f"warning: no uv in >={UV_MIN_VERSION},<{UV_MAX_VERSION} to replace "
            f"{', '.join(str(path) for path in legacy)}; re-run install-parrot --global"
        )
        return log
    for path in legacy:
        if path.is_symlink() or path.exists():
            path.unlink()
            log.append(f"removed legacy {path} (it shadowed the uv on your PATH)")
    return log
```
**Why**: Guards `os.replace` with `not bin_uv.is_symlink()`, resolves and records a compatible external `uv` when `bin/uv` was symlinked to the user's binary without a separate `PATH` entry, and unlinks only the legacy symlink.

### `packages/ai-parrot/tests/self_/test_uv.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_migrate_keeps_files_when_nothing_is_compatible(home: Path) -> None:' packages/ai-parrot/tests/self_/test_uv.py)
# AFTER — insert below `test_migrate_keeps_files_when_nothing_is_compatible` (packages/ai-parrot/tests/self_/test_uv.py:120-124):
@posix_only
def test_migrate_unlinks_symlink_without_moving_user_uv(home: Path, tmp_path: Path) -> None:
    """A legacy bin/uv symlink to the user's uv is unlinked without moving the target into libexec."""
    user_uv = _fake_uv(tmp_path / "user-bin" / "uv", "0.11.30")
    before = (user_uv.read_bytes(), user_uv.stat().st_mtime_ns)
    link = home / "bin" / "uv"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(user_uv)
    log = uv.migrate_legacy_uv()
    assert not link.exists() and not link.is_symlink()
    assert not uv.managed_uv().exists()
    assert user_uv.is_file() and (user_uv.read_bytes(), user_uv.stat().st_mtime_ns) == before
    assert uv.read_recorded_uv() == user_uv.resolve()
    assert any("removed legacy" in entry for entry in log)
```
**Why**: Verifies that a symlink at `bin/uv` is unlinked, `managed_uv()` is not populated by moving the symlink or target, the user's binary is untouched, and its path is recorded.

### FILL IN checklist
- [ ] `packages/ai-parrot/src/parrot/self_/uv.py::migrate_legacy_uv` — guard symlink move and unlink link only
- [ ] `packages/ai-parrot/tests/self_/test_uv.py::test_migrate_unlinks_symlink_without_moving_user_uv` — test symlink guard

---

## Acceptance Criteria

- [ ] `legacy_uv_files()` includes symlinks under `parrot_home() / "bin"`.
- [ ] `migrate_legacy_uv()` never calls `os.replace` on a symlinked `bin/uv`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/self_/test_uv.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/self_/uv.py packages/ai-parrot/tests/self_/test_uv.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/self_/test_uv.py -q`

---

## Test Specification

See Implementation Blueprint above (`test_migrate_unlinks_symlink_without_moving_user_uv`).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug self--uv-fixes --feature-id FEAT-872`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in `sdd/tasks/index/self--uv-fixes.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — follow the Implementation Blueprint
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5465 self--uv-fixes verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
