---
type: Wiki Overview
title: 'TASK-1081: Emit `--config=<path>` from `_build_cli_args`'
id: doc:sdd-tasks-completed-task-1081-cloudsploit-cli-config-arg-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per FEAT-160 proposal §3 ("What Changes" → second bullet) and §2.1 (Localization
---

# TASK-1081: Emit `--config=<path>` from `_build_cli_args`

**Feature**: FEAT-160 — CloudSploit `--config` support for run_scan
**Spec**: `sdd/proposals/cloudsploit-config-support.proposal.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Per FEAT-160 proposal §3 ("What Changes" → second bullet) and §2.1 (Localization
row 2): `_build_cli_args` currently never emits `--config`. Add a `config_path`
kwarg and, when set, prepend `--config=<config_path>` to the args list (before
`--cloud=`, for readability).

This task is the lowest-level wiring; downstream tasks (TASK-1082) call it.

---

## Scope

- Add `config_path: Optional[str] = None` parameter to `_build_cli_args`.
- When `config_path` is non-empty, prepend `f"--config={config_path}"` as the
  first element of `args` (before `--json=...`, `--console=none`, `--cloud=...`).
- When `config_path` is None, behaviour is unchanged — no `--config` argv element
  appears.
- Argv tests in `tests/cloudsploit/test_executor.py`.

**NOT in scope**:
- Validating that the file at `config_path` exists — that's TASK-1082's job
  inside `_run_with_outputs`.
- Computing the in-container path — `_build_cli_args` receives the path
  already-rewritten by the caller (TASK-1082).
- Any volume-mount logic — TASK-1080.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py` | MODIFY | Add `config_path` kwarg to `_build_cli_args`; prepend `--config=` |
| `packages/ai-parrot-tools/tests/cloudsploit/test_executor.py` | MODIFY | Add 2-3 argv tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in executor.py — no new imports needed
from typing import Optional
from .models import CloudProvider, CloudSploitConfig, ComplianceFramework
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:109-151
def _build_cli_args(
    self,
    json_path: str,
    collection_path: Optional[str] = None,
    plugins: Optional[list[str]] = None,
    compliance: Optional[ComplianceFramework] = None,
    ignore_ok: bool = False,
    suppress: Optional[list[str]] = None,
) -> list[str]:
    args = [
        f"--json={json_path}",
        "--console=none",
        f"--cloud={self.config.cloud_provider.value}",
    ]
    if collection_path:
        args.append(f"--collection={collection_path}")
    if compliance:
        args.append(f"--compliance={compliance.value}")
    # ... etc
    return args
```

### Does NOT Exist
- ~~`--config-file` as the CLI flag~~ — upstream uses `--config` (no suffix).
- ~~`--config` as a positional argument~~ — it's a `--config=<value>` kv pair.
- ~~`self.config.config_file`~~ — does not exist YET (TASK-1079 adds it). This
  task does NOT read it; the caller (TASK-1082) is responsible for resolving
  the effective path.

---

## Implementation Notes

### Pattern to Follow
```python
def _build_cli_args(
    self,
    json_path: str,
    collection_path: Optional[str] = None,
    plugins: Optional[list[str]] = None,
    compliance: Optional[ComplianceFramework] = None,
    ignore_ok: bool = False,
    suppress: Optional[list[str]] = None,
    config_path: Optional[str] = None,   # <-- new
) -> list[str]:
    args: list[str] = []
    if config_path:
        args.append(f"--config={config_path}")  # FIRST, so it's clearly visible in logs
    args.extend([
        f"--json={json_path}",
        "--console=none",
        f"--cloud={self.config.cloud_provider.value}",
    ])
    # ... rest unchanged
```

### Key Constraints
- Use `f"--config={config_path}"` (key=value form) — matches the rest of the
  builder. Do NOT use `--config <path>` (two-arg form).
- The `--config` element MUST appear at index 0 when present, before `--json=`.
- Empty string `""` is treated the same as `None` (no flag emitted).
- Update the docstring to mention the new kwarg.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:131-148` — existing
  pattern of conditional flag append (`--collection=`, `--compliance=`, etc.).
- aquasecurity/cloudsploit README §usage block (the F005 finding cited in the
  proposal) confirms the `--config=<path>` form.

---

## Acceptance Criteria

- [ ] `_build_cli_args(json_path="/tmp/r.json")` returns args with NO `--config`
      element (default behaviour unchanged).
- [ ] `_build_cli_args(json_path="/tmp/r.json", config_path="/c/cs.js")` returns
      args whose first element is `"--config=/c/cs.js"`.
- [ ] `_build_cli_args(json_path="/tmp/r.json", config_path="")` returns args
      with NO `--config` element.
- [ ] All other args (`--cloud=`, `--json=`, `--console=none`, `--collection=`,
      etc.) still emitted in the same relative order as before.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py` clean.

---

## Test Specification

```python
def test_cli_args_no_config_when_none():
    e = CloudSploitExecutor(CloudSploitConfig())
    args = e._build_cli_args(json_path="/tmp/r.json")
    assert not any(a.startswith("--config=") for a in args)


def test_cli_args_config_first():
    e = CloudSploitExecutor(CloudSploitConfig())
    args = e._build_cli_args(json_path="/tmp/r.json",
                             config_path="/cs/config.js")
    assert args[0] == "--config=/cs/config.js"


def test_cli_args_empty_config_omitted():
    e = CloudSploitExecutor(CloudSploitConfig())
    args = e._build_cli_args(json_path="/tmp/r.json", config_path="")
    assert not any(a.startswith("--config=") for a in args)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the proposal** §3 ("What Changes" → executor argv).
2. **Verify the Codebase Contract** by reading `executor.py:109-151`.
3. **Implement** the kwarg + conditional prepend per the pattern above.
4. **Run tests**: `pytest packages/ai-parrot-tools/tests/cloudsploit/test_executor.py -v`.
5. **Move this file** to `sdd/tasks/completed/`.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-12
**Notes**: Added `config_path: Optional[str] = None` kwarg to `_build_cli_args`. When set (non-empty), prepends `--config=<path>` as the first element. Empty string treated the same as None. Updated docstring. 4 new tests pass.

**Deviations from spec**: none
