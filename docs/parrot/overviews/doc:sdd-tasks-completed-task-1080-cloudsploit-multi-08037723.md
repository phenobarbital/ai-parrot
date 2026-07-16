---
type: Wiki Overview
title: 'TASK-1080: Widen `_build_docker_command.volume_mount` to accept multiple mounts'
id: doc:sdd-tasks-completed-task-1080-cloudsploit-multi-volume-mount-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per FEAT-160 proposal §2.2 ("Existing volume-mount slot is single-tuple")
  and §3
---

# TASK-1080: Widen `_build_docker_command.volume_mount` to accept multiple mounts

**Feature**: FEAT-160 — CloudSploit `--config` support for run_scan
**Spec**: `sdd/proposals/cloudsploit-config-support.proposal.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Per FEAT-160 proposal §2.2 ("Existing volume-mount slot is single-tuple") and §3
("What Changes" → third bullet): the executor's `_build_docker_command` and
`execute()` accept a single `Optional[tuple[str, str]]` for the bind-mount. To
support BOTH the output dir AND the config-file dir simultaneously, we must widen
this to a list of mount specs that also carries an optional mode flag (`"ro"` /
`"rw"`).

This is a contained internal refactor — `_run_with_outputs` is the only in-tree
caller of these methods. It must be migrated atomically.

---

## Scope

- Change `volume_mount` parameter type on `_build_docker_command` and `execute`
  from `Optional[tuple[str, str]]` to
  `Optional[list[tuple[str, str, Optional[str]]]]` where each tuple is
  `(host_dir, container_dir, mode)` with `mode in {None, "ro", "rw"}`.
- In `_build_docker_command`, emit `-v host:container` when mode is None, and
  `-v host:container:ro` (or `:rw`) when mode is set.
- Update the single existing caller `_run_with_outputs` (line 274) to pass a
  list with one element instead of a bare tuple.
- Update or add tests in `tests/cloudsploit/test_executor.py` that cover
  multi-mount construction and the `:ro` suffix.

**NOT in scope**:
- Adding any `--config` flag emission — TASK-1081.
- Adding the config-file mount itself — TASK-1082.
- Any toolkit-level changes — TASK-1083.
- Backwards-compat shim for the old single-tuple form (migrate the single
  caller atomically — no other code in-tree depends on the old shape).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py` | MODIFY | Widen `volume_mount` on `_build_docker_command`, `execute`; update `_run_with_outputs` callsite |
| `packages/ai-parrot-tools/tests/cloudsploit/test_executor.py` | MODIFY | Add tests for multi-mount + `:ro` suffix; update any existing tests using the old single-tuple form |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in executor.py — no new imports needed
import asyncio, os, re, tempfile
from pathlib import Path
from typing import Optional
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:15
_DOCKER_OUTPUT_MOUNT = "/cloudsploit/output"

# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:59-83
def _build_docker_command(
    self,
    args: list[str],
    volume_mount: Optional[tuple[str, str]] = None,  # <-- WIDEN THIS
) -> list[str]:
    cmd = ["docker", "run", "--rm"]
    if volume_mount:
        host_dir, container_dir = volume_mount
        cmd.extend(["-v", f"{host_dir}:{container_dir}"])
    ...

# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:186-205
async def execute(
    self,
    args: list[str],
    volume_mount: Optional[tuple[str, str]] = None,  # <-- WIDEN THIS
) -> tuple[str, str, int]:
    ...
    if self.config.use_docker:
        cmd = self._build_docker_command(args, volume_mount=volume_mount)

# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:263-292
# Single in-tree caller — must be migrated atomically:
async def _run_with_outputs(...):
    ...
    volume_mount = (str(host_dir), _DOCKER_OUTPUT_MOUNT)  # <-- BECOMES list
    ...
    stdout, stderr, exit_code = await self.execute(
        args, volume_mount=volume_mount,
    )
```

### Does NOT Exist
- ~~`docker run --volume=`~~ — use `-v` flag (consistent with current code).
- ~~A "deprecated" warning hook on `volume_mount`~~ — don't add backwards-compat,
  just migrate the one caller.
- ~~A `VolumeMount` Pydantic model~~ — keep it as a plain tuple type.

---

## Implementation Notes

### Pattern to Follow
```python
# Target signature for _build_docker_command:
def _build_docker_command(
    self,
    args: list[str],
    volume_mounts: Optional[list[tuple[str, str, Optional[str]]]] = None,
) -> list[str]:
    cmd = ["docker", "run", "--rm"]
    for mount in volume_mounts or []:
        host_dir, container_dir, mode = mount
        spec = f"{host_dir}:{container_dir}"
        if mode:
            spec = f"{spec}:{mode}"
        cmd.extend(["-v", spec])
    ...
```

The parameter NAME may stay `volume_mount` (singular) for blast-radius reasons,
or be renamed `volume_mounts` (plural). Pick one and apply consistently across
`_build_docker_command`, `execute`, and the docstrings. Recommended: **rename to
`volume_mounts`** so the type/intent are obvious at call sites.

### Key Constraints
- The mode element is `Optional[str]` — `None`, `"ro"`, or `"rw"`. No other values.
- Order of `-v` flags matches list order (Docker tolerates either, but be deterministic).
- `_run_with_outputs` must be updated in the same commit.
- Do not change `_build_env_vars`, `_build_cli_args`, or any other helper.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:59-83` — current implementation.
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:263-292` — sole caller.
- `packages/ai-parrot-tools/src/parrot_tools/security/base_executor.py` — comparable pattern (separate codebase but informative).

---

## Acceptance Criteria

- [ ] `_build_docker_command(args, volume_mounts=None)` emits `["docker","run","--rm",...]`
      with no `-v` flag.
- [ ] `_build_docker_command(args, volume_mounts=[("/a","/b",None)])` includes `-v /a:/b`.
- [ ] `_build_docker_command(args, volume_mounts=[("/a","/b","ro")])` includes `-v /a:/b:ro`.
- [ ] `_build_docker_command(args, volume_mounts=[("/a","/b",None),("/c","/d","ro")])`
      includes BOTH mounts in order.
- [ ] `_run_with_outputs` continues to work end-to-end with the new list-based mount.
- [ ] All existing tests in `tests/cloudsploit/test_executor.py` still pass after
      the migration.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py` clean.

---

## Test Specification

```python
def test_docker_command_no_mount():
    cfg = CloudSploitConfig()
    e = CloudSploitExecutor(cfg)
    cmd = e._build_docker_command(["--cloud=aws"], volume_mounts=None)
    assert "-v" not in cmd


def test_docker_command_single_mount():
    e = CloudSploitExecutor(CloudSploitConfig())
    cmd = e._build_docker_command(["--cloud=aws"],
                                  volume_mounts=[("/h", "/c", None)])
    assert cmd.count("-v") == 1
    assert "/h:/c" in cmd


def test_docker_command_read_only_mount():
    e = CloudSploitExecutor(CloudSploitConfig())
    cmd = e._build_docker_command(["--cloud=aws"],
                                  volume_mounts=[("/h", "/c", "ro")])
    assert "/h:/c:ro" in cmd


def test_docker_command_multi_mount_order():
    e = CloudSploitExecutor(CloudSploitConfig())
    cmd = e._build_docker_command(
        ["--cloud=aws"],
        volume_mounts=[("/o", "/cloudsploit/output", None),
                       ("/cfgdir", "/cloudsploit/config", "ro")],
    )
    o_idx = cmd.index("/o:/cloudsploit/output")
    c_idx = cmd.index("/cfgdir:/cloudsploit/config:ro")
    assert o_idx < c_idx
```

---

## Agent Instructions

When you pick up this task:

1. **Read the proposal** §2.2 and §3 ("What Changes" → `_build_docker_command`).
2. **Verify the Codebase Contract** by reading `executor.py:59-83`, `186-231`, and
   `263-292`.
3. **Implement** the type widening on both methods and update the single caller.
4. **Run tests**: `pytest packages/ai-parrot-tools/tests/cloudsploit/ -v`.
5. **Move this file** to `sdd/tasks/completed/`.
6. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-12
**Notes**: Renamed parameter from `volume_mount` to `volume_mounts` on both `_build_docker_command` and `execute`. Updated `_run_with_outputs` to pass a list with one element. Added 4 new tests covering no-mount, single-mount, read-only suffix, and multi-mount order. All new tests pass; only pre-existing env-specific failures remain.

**Deviations from spec**: none
