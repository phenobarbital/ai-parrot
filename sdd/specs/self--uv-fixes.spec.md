---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [sdd, launcher, uv, ledger-fix]
docs:
  policy: none
---

# Feature Specification: Guard `migrate_legacy_uv` Against Symlinked Legacy `bin/uv`

**Feature ID**: FEAT-872
**Date**: 2026-11-10
**Author**: /sdd-fix (agent:sdd-fix:3a25996f)
**Status**: approved
**Target version**: 2.1.3

**Discovered-from**: `issue:d08792fd4747`

> Ledger-driven fix. Drains `/sdd-fix` group `fixgroup:4c9c835b3de5` (`issue:d08792fd4747`, minor bug), discovered during review of `HOTFIX-installer-uv-shadowing-1`.

---

## 1. Motivation & Business Requirements

### Problem Statement

In `packages/ai-parrot/src/parrot/self_/uv.py`, `legacy_uv_files()` checks `(bin_dir / _exe("uv"), bin_dir / _exe("uvx"))` using `path.is_file()`. Because `Path.is_file()` follows symlinks, a symlink at `~/.parrot/bin/uv` (or `uvx`) pointing to the user's own `uv` installation is returned as a legacy file.

When `migrate_legacy_uv()` runs and no managed, recorded, or separate `PATH` `uv` is found—for example when the user's `uv` is only exposed via that `~/.parrot/bin/uv` symlink or `PATH` only includes `~/.parrot/bin`—the branch `elif bin_uv in legacy and _compatible(bin_uv):` executes `os.replace(bin_uv, managed_uv())`. Moving a symlink into `~/.parrot/libexec/uv` and treating it as a private managed binary is wrong (or if `bin/uv` is a symlink to a file on another filesystem, `os.replace` raises `EXDEV`; if on the same filesystem, it relocates the symlink into `libexec` instead of owning a standalone managed binary, or unlinks it without recording the target if broken). Moreover, a broken symlink at `~/.parrot/bin/uv` has `is_file() == False` and `exists() == False`, so `legacy_uv_files()` and the cleanup loop `if path.exists(): path.unlink()` both miss it.

The issue contract (`issue:d08792fd4747`) states:
> `packages/ai-parrot/src/parrot/self_/uv.py`: `legacy_uv_files()` uses `is_file()`, which follows symlinks, and `migrate_legacy_uv` may `os.replace` the file when in range. A legacy `bin/uv` symlink to the user's own `uv` would be moved. Guard with `is_symlink()` and unlink the link only.

### Goals
- Include symlinks (even dangling ones) in `legacy_uv_files()` alongside regular files (`path.is_symlink() or path.is_file()`).
- In `migrate_legacy_uv()`, never `os.replace(bin_uv, managed_uv())` when `bin_uv.is_symlink()` is true. If `bin_uv` is a symlink whose resolved target (outside `parrot_home()/bin` and `libexec_dir()`) is a compatible `uv`, record that resolved target via `record_system_uv(target)` and unlink the legacy symlink; otherwise only unlink the symlink (or warn if no replacement `uv` exists and a non-symlink legacy copy would be lost, while never moving a symlink into `libexec`). Specifically, when `bin_uv` is a symlink and no managed/recorded/PATH `uv` is already selected:
  - If `bin_uv` is a symlink pointing to an external compatible binary (`not bin_uv.is_symlink()` is required for moving into `managed_uv()`, whereas a symlink to an external compatible binary can either be recorded if its resolved target is outside `parrot_home()` or unlinked when another replacement exists).
  - Wait: let's check both cases cleanly:
    1. Guard the `os.replace` branch with `not bin_uv.is_symlink()`: `elif bin_uv in legacy and not bin_uv.is_symlink() and _compatible(bin_uv):`.
    2. What if `bin_uv` is a symlink to the user's own compatible `uv` (e.g. `/opt/user/uv` not on `PATH`), and no managed/recorded/PATH `uv` was found? If we resolve the symlink target (`target = bin_uv.resolve()`) and it is outside `parrot_home()` and `_compatible(target)`, recording `target` with `record_system_uv(target)` and unlinking the `bin/uv` symlink preserves the user's `uv` as recorded AND unlinks the legacy link without moving or touching the target binary! And if a symlink at `bin/uv` is unlinked in the cleanup loop, use `if path.is_symlink() or path.exists(): path.unlink()` so dangling symlinks are also unlinked cleanly.

### Non-Goals (explicitly out of scope)
- Changing `resolve_uv()`, `record_system_uv()`, or `find_path_uv()` semantics.
- Modifying installer shell scripts or CLI entrypoints.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:b4d1136d6962bed81615478e219e3dc2f7e345875754223cc10556c463929684 evaluation_digest=sha256:073023b5091129b67b8577acc124c880da311bd8c072bbb737f372c3304a0c1c rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Two functions in `packages/ai-parrot/src/parrot/self_/uv.py` are updated:

1. `legacy_uv_files()`:
   Detect legacy `uv` and `uvx` entries under `parrot_home() / "bin"` when `path.is_symlink() or path.is_file()`, so both regular files and symlinks (live or broken) are recognized.

2. `migrate_legacy_uv()`:
   - Never move a symlink into `managed_uv()`: guard the move branch with `elif bin_uv in legacy and not bin_uv.is_symlink() and _compatible(bin_uv):`.
   - When `bin_uv in legacy and bin_uv.is_symlink()` and no managed/recorded/PATH `uv` was already matched: check if the symlink target (`target = bin_uv.resolve(strict=False)`) is outside `{_resolved(parrot_home() / "bin"), _resolved(libexec_dir())}` and `_compatible(target)`. If so, record `target` via `record_system_uv(target)` and log `f"using your uv at {target}: recorded in {uv_path_file()}"`, then proceed to the unlink loop so only the symlink at `bin/uv` is unlinked while the target file is untouched. If the symlink target is not compatible (or is broken) and all `legacy` entries are symlinks, unlink the broken/incompatible legacy symlinks (or if any legacy entry is a non-symlink file with no compatible replacement, keep the warning behavior). Wait—let's check what happens if `bin/uv` is a symlink to a compatible user `uv` vs incompatible:
     - Case 1: Compatible managed, recorded, or `PATH` `uv` exists → `migrate_legacy_uv` records `PATH` `uv` (if needed) and unlinks `legacy` entries (`if path.is_symlink() or path.exists(): path.unlink()`).
     - Case 2: No managed, recorded, or `PATH` `uv`, and `bin_uv` is a symlink to a compatible external `uv` → `record_system_uv(target)` records the target, and the cleanup loop unlinks `bin_uv` (the symlink only; `target` remains intact at its original path, and `managed_uv()` is not created).
     - Case 3: No managed, recorded, or `PATH` `uv`, and `bin_uv` is a regular file (`not bin_uv.is_symlink()`) that is `_compatible(bin_uv)` → `os.replace(bin_uv, managed_uv())` moves it to `libexec`.
     - Case 4: Otherwise → emit the warning and return `log` without unlinking.
   - In the cleanup loop at the end of `migrate_legacy_uv()`, check `if path.is_symlink() or path.exists(): path.unlink()` so symlinks (including broken ones when a replacement `uv` was found) are unlinked without following the link.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.self_.uv.legacy_uv_files` | modifies | includes `path.is_symlink() or path.is_file()` |
| `parrot.self_.uv.migrate_legacy_uv` | modifies | guards `os.replace` with `not bin_uv.is_symlink()`, records compatible symlink target, unlinks symlink only |

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Symlink guard in `migrate_legacy_uv` | no | Single-module fix implemented directly in the `/sdd-fix` session | Direct session implementation |

### Module 1: Symlink guard in `migrate_legacy_uv`
- **Path**: `packages/ai-parrot/src/parrot/self_/uv.py`
- **Responsibility**: Ensure `legacy_uv_files()` and `migrate_legacy_uv()` do not follow symlinks when moving legacy `bin/uv` into `libexec`, unlinking only the symlink while preserving the user's underlying `uv` binary.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/self_/uv.py (modifies :65-69 and :174-200)
  def legacy_uv_files() -> list[Path]:
      """Return legacy uv and uvx files or symlinks under ``parrot_home()/bin``."""

  def migrate_legacy_uv() -> list[str]:
      """Move a legacy bin uv layout into libexec or record a compatible system uv."""
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_migrate_unlinks_symlink_without_moving_target` | Module 1 | When `bin/uv` is a symlink to the user's `uv` (both with and without `PATH` entry), `migrate_legacy_uv()` unlinks only `bin/uv`, never moves it to `managed_uv()`, and leaves the user's target binary intact |
| Existing `test_uv.py` suite | Module 1 | All existing resolution and migration tests continue to pass |

### Validation Contract

tests:
- packages/ai-parrot/tests/self_/test_uv.py
markers: none

## 5. Acceptance Criteria

- [ ] `legacy_uv_files()` detects symlinks as well as regular files under `parrot_home() / "bin"`.
- [ ] `migrate_legacy_uv()` guards `os.replace(bin_uv, managed_uv())` with `not bin_uv.is_symlink()`, never moving a symlink into `libexec`.
- [ ] When `bin/uv` is a symlink to a compatible user `uv` (even if not on `PATH`), `migrate_legacy_uv()` records the resolved target in `uv-path`, unlinks only the `bin/uv` symlink, and leaves the user's `uv` binary untouched.
- [ ] All tests in `packages/ai-parrot/tests/self_/test_uv.py` pass and `ruff check` is clean on modified files.

---

## 6. Codebase Contract

Verified against `origin/dev` @ `2e35d887fa`.

### Verified Imports
```python
from parrot.launcher import parrot_home  # verified: packages/ai-parrot/src/parrot/self_/uv.py:15
from parrot.self_ import uv  # verified: packages/ai-parrot/tests/self_/test_uv.py:10
```

### Existing Class Signatures
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

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `migrate_legacy_uv` | `record_system_uv`, `managed_uv`, `legacy_uv_files` | function call | `packages/ai-parrot/src/parrot/self_/uv.py:174` |

### Does NOT Exist (Anti-Hallucination)
- No external symlink helper outside `pathlib.Path.is_symlink` / `Path.resolve`.

### Edit Sites (Blueprint Anchors)

Verified against: `2e35d887fa`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/self_/uv.py` | MODIFY | `def legacy_uv_files() -> list[Path]:` | `uv.py:65` | 1 |
| `packages/ai-parrot/src/parrot/self_/uv.py` | MODIFY | `def migrate_legacy_uv() -> list[str]:` | `uv.py:174` | 1 |
| `packages/ai-parrot/tests/self_/test_uv.py` | MODIFY | `def test_migrate_keeps_files_when_nothing_is_compatible(home: Path) -> None:` | `test_uv.py:120` | 1 |

---

## 7. Implementation Notes & Constraints

- Keep the diff minimal and confined to `packages/ai-parrot/src/parrot/self_/uv.py` and `packages/ai-parrot/tests/self_/test_uv.py`.
- Ledger linkage: `issue:d08792fd4747`.

## Worktree Strategy
Single feature worktree (`feat-FEAT-872-self--uv-fixes`), single task.

## Decisions

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:b4d1136d6962bed81615478e219e3dc2f7e345875754223cc10556c463929684 evaluation_digest=sha256:073023b5091129b67b8577acc124c880da311bd8c072bbb737f372c3304a0c1c rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/self--uv-fixes.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: launcher, ledger-fix, uv
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "sdd-tooling",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "launcher",
      "ledger-fix",
      "uv"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/self--uv-fixes.spec.md"
    }
  ],
  "evaluation_digest": "sha256:073023b5091129b67b8577acc124c880da311bd8c072bbb737f372c3304a0c1c",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:b4d1136d6962bed81615478e219e3dc2f7e345875754223cc10556c463929684",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Should a legacy `bin/uv` symlink to a compatible user `uv` (not otherwise on `PATH`) record the resolved user `uv` before unlinking the symlink? — *Resolved*: Yes, resolving the symlink target and recording it when compatible and outside `parrot_home()/bin` and `libexec_dir()` avoids breaking a setup where the user symlinked `~/.parrot/bin/uv -> /path/to/user/uv`, while still unlinking only the legacy symlink and never moving anything into `libexec`.

---

## 9. Design Research Cross-Check

Status: skipped (ledger-driven minor bugfix from `/sdd-fix`, no exploration doc)

---

## 10. Documentation

- **Policy**: `none`

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-10 | /sdd-fix (`agent:sdd-fix:3a25996f`) | Initial spec from `fixgroup:4c9c835b3de5` (`issue:d08792fd4747`) |
